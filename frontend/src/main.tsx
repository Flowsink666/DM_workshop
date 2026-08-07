import React, { FormEvent, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Archive, Backpack, Coins, History, Plus, RefreshCw, RotateCcw,
  Shield, Store, Swords, UserRound, UsersRound, X,
} from "lucide-react";
import "./styles.css";
import "./mobile-fixes.css";

type Json = Record<string, any>;
type Tab = "overview" | "actors" | "inventory" | "shops" | "combat" | "history";
type Command = (name: string, body: Json) => Promise<Json | null>;

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  // 所有页面操作统一解析后端错误，避免各视图出现不同的失败提示格式。
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `请求失败 (${response.status})`);
  return body as T;
}

const tabs: Array<[Tab, string, React.ElementType]> = [
  ["overview", "总览", Archive], ["actors", "角色", UsersRound],
  ["inventory", "背包", Backpack], ["shops", "交易", Store],
  ["combat", "战斗", Swords], ["history", "记录", History],
];

function App() {
  const [campaigns, setCampaigns] = useState<Json[]>([]);
  const [campaignId, setCampaignId] = useState("");
  const [state, setState] = useState<Json | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const refreshCampaigns = async () => {
    const rows = await api<Json[]>("/api/campaigns");
    setCampaigns(rows);
    if (!campaignId && rows.length) setCampaignId(rows[0].id);
  };
  const refresh = async () => {
    if (!campaignId) return;
    setState(await api<Json>(`/api/campaigns/${campaignId}`));
  };
  useEffect(() => { refreshCampaigns().catch(showError); }, []);
  useEffect(() => { refresh().catch(showError); }, [campaignId]);

  function showError(value: unknown) {
    setError(value instanceof Error ? value.message : String(value));
  }
  async function command(name: string, body: Json): Promise<Json | null> {
    // Web 与 MCP 走同一命令服务；前端成功后重新读取权威状态，不做乐观拼接。
    if (!campaignId) return null;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await api<Json>(`/api/campaigns/${campaignId}/commands/${name}`, {
        method: "POST", body: JSON.stringify(body),
      });
      setNotice(`已执行，操作 ID ${result.operation_id.slice(0, 8)}`);
      await refresh(); await refreshCampaigns();
      return result;
    } catch (reason) { showError(reason); return null; }
    finally { setBusy(false); }
  }
  async function createCampaign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const name = String(form.get("name") || "").trim();
    if (!name) return;
    setBusy(true);
    try {
      const created = await api<Json>("/api/campaigns", {
        method: "POST", body: JSON.stringify({ name }),
      });
      formElement.reset();
      await refreshCampaigns(); setCampaignId(created.id);
    } catch (reason) { showError(reason); }
    finally { setBusy(false); }
  }

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><Shield size={22}/><div><strong>DM Workshop</strong><span>5e 2014 权威状态</span></div></div>
      <div className="side-label">战役</div>
      <nav className="campaign-list">
        {campaigns.map(c => <button key={c.id} className={campaignId === c.id ? "active" : ""}
          onClick={() => setCampaignId(c.id)}><span>{c.name}</span><small>r{c.revision}</small></button>)}
        {!campaigns.length && <p className="empty-side">还没有战役</p>}
      </nav>
      <form className="new-campaign" onSubmit={createCampaign}>
        <input name="name" placeholder="新战役名称" aria-label="新战役名称" />
        <button className="icon-button" title="创建战役" disabled={busy}><Plus size={17}/></button>
      </form>
      <div className="connection"><span></span>MCP / Web 共用本地数据</div>
    </aside>
    <main>
      <header className="topbar">
        <div><h1>{state?.name || "选择一个战役"}</h1>{state && <span>修订 {state.revision} · {state.ruleset}</span>}</div>
        <button className="icon-button ghost" title="刷新" onClick={() => refresh().catch(showError)}><RefreshCw size={18}/></button>
      </header>
      <nav className="tabs">
        {tabs.map(([id, label, Icon]) => <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>
          <Icon size={16}/>{label}</button>)}
      </nav>
      {(error || notice) && <div className={`message ${error ? "error" : "notice"}`}>
        <span>{error || notice}</span><button title="关闭" onClick={() => {setError("");setNotice("");}}><X size={16}/></button>
      </div>}
      <section className="content">
        {!state ? <Empty title="选择或创建战役"/> : <>
          {tab === "overview" && <Overview state={state}/>} 
          {tab === "actors" && <Actors state={state} command={command}/>} 
          {tab === "inventory" && <Inventory state={state} command={command}/>} 
          {tab === "shops" && <Shops state={state} command={command}/>} 
          {tab === "combat" && <Combat state={state} command={command}/>} 
          {tab === "history" && <Operations campaignId={campaignId} revision={state.revision} refresh={refresh} showError={showError}/>} 
        </>}
      </section>
    </main>
    {busy && <div className="busy" aria-label="正在处理"><RefreshCw size={22}/></div>}
  </div>;
}

function Overview({state}: {state: Json}) {
  const actors = Object.values(state.actors) as Json[];
  const alive = actors.filter(a => a.life_state !== "dead").length;
  const inventoryCount = actors.reduce((n, a) => n + Object.keys(a.inventory).length, 0);
  const active = (Object.values(state.encounters) as Json[]).find(e => e.status === "active");
  return <div className="overview">
    <div className="metrics">
      <Metric icon={UsersRound} label="角色" value={`${alive} / ${actors.length}`} detail="存活 / 总数"/>
      <Metric icon={Backpack} label="物品栈" value={String(inventoryCount)} detail="角色背包"/>
      <Metric icon={Store} label="商店" value={String(Object.keys(state.shops).length)} detail="可交易地点"/>
      <Metric icon={Swords} label="遭遇" value={active ? `第 ${active.round} 轮` : "无"} detail={active?.name || "当前没有战斗"}/>
    </div>
    <div className="section-head"><div><h2>队伍状态</h2><p>生命、护甲与资源概览</p></div></div>
    <div className="actor-grid">{actors.map(actor => <ActorRow key={actor.id} actor={actor}/>)}</div>
  </div>;
}

function Metric({icon: Icon,label,value,detail}: any) {
  return <div className="metric"><Icon size={19}/><div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div></div>;
}
function ActorRow({actor}: {actor: Json}) {
  const hpPct = Math.max(0, Math.min(100, actor.hp / actor.max_hp * 100));
  return <div className="actor-row">
    <div className="avatar">{actor.name.slice(0,1)}</div>
    <div className="actor-main"><strong>{actor.name}</strong><span>{actor.kind.toUpperCase()} · 等级 {actor.level}</span>
      <div className="hp-track"><i style={{width: `${hpPct}%`}}/></div></div>
    <b>{actor.hp}/{actor.max_hp} HP</b><em>AC {actor.ac}</em><Status value={actor.life_state}/>
  </div>;
}
function Status({value}: {value: string}) {
  const labels: Json = {conscious:"清醒", unconscious:"昏迷", stable:"稳定", dead:"死亡"};
  return <span className={`status ${value}`}>{labels[value] || value}</span>;
}
function money(cp:number) {const gp=Math.floor(cp/100), sp=Math.floor(cp%100/10), rest=cp%10;return `${gp} GP ${sp} SP ${rest} CP`}

function Actors({state, command}: {state: Json, command: Command}) {
  const [selected, setSelected] = useState("");
  const actors = Object.values(state.actors) as Json[];
  const actor = state.actors[selected] || actors[0];
  useEffect(() => { if (!selected && actors[0]) setSelected(actors[0].id); }, [actors.length]);
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const formElement = event.currentTarget; const f = new FormData(formElement);
    const result = await command("create_actor", {name:f.get("name"), kind:f.get("kind"), level:Number(f.get("level")), max_hp:Number(f.get("max_hp")), ac:Number(f.get("ac"))});
    if (result) formElement.reset();
  }
  return <div className="split-view"><div className="list-pane">
    <div className="section-head"><div><h2>角色</h2><p>{actors.length} 个战役实体</p></div></div>
    {actors.map(a => <button key={a.id} className={`entity-button ${actor?.id===a.id?"active":""}`} onClick={()=>setSelected(a.id)}>
      <span className="avatar small">{a.name.slice(0,1)}</span><span><strong>{a.name}</strong><small>{a.kind} · Lv.{a.level}</small></span><Status value={a.life_state}/></button>)}
  </div><div className="detail-pane">
    {actor ? <CharacterSheet actor={actor} command={command}/> : <Empty title="尚无角色"/>}
    <form className="inline-form create-actor" onSubmit={create}>
      <h3>添加角色</h3><input name="name" placeholder="名称" required/><select name="kind"><option value="pc">PC</option><option value="npc">NPC</option><option value="monster">怪物</option></select>
      <input name="level" type="number" defaultValue="1" min="1" max="20"/><input name="max_hp" type="number" defaultValue="10" min="1"/><input name="ac" type="number" defaultValue="10" min="1"/>
      <button><Plus size={15}/>添加</button>
    </form>
  </div></div>;
}
function CharacterSheet({actor, command}: {actor: Json, command: Command}) {
  const abilities = Object.entries(actor.abilities) as [string,number][];
  const [amount,setAmount] = useState(1);
  return <><div className="sheet-title"><div><h2>{actor.name}</h2><p>{actor.id}</p></div><Status value={actor.life_state}/></div>
    <div className="vitals"><span><small>HP</small><b>{actor.hp}/{actor.max_hp}</b></span><span><small>临时 HP</small><b>{actor.temp_hp}</b></span><span><small>AC</small><b>{actor.ac}</b></span><span><small>速度</small><b>{actor.speed}</b></span><span><small>货币</small><b>{money(actor.wallet_cp)}</b></span></div>
    <div className="ability-grid">{abilities.map(([key,value]) => <div key={key}><span>{key}</span><strong>{value}</strong><small>{Math.floor((value-10)/2)>=0?"+":""}{Math.floor((value-10)/2)}</small></div>)}</div>
    <div className="quick-actions"><input type="number" min="0" value={amount} onChange={e=>setAmount(Number(e.target.value))}/><button className="danger" onClick={()=>command("apply_damage",{actor_id:actor.id,amount})}>扣除 HP</button><button onClick={()=>command("heal",{actor_id:actor.id,amount})}>治疗</button><button onClick={()=>command("rest",{actor_id:actor.id,rest_type:"long"})}>长休</button></div>
    <div className="condition-line"><strong>状态</strong>{Object.keys(actor.conditions).length ? Object.keys(actor.conditions).map(c=><span key={c}>{c}</span>) : <small>无</small>}</div>
  </>;
}

function Inventory({state, command}: {state: Json, command: Command}) {
  const actors = Object.values(state.actors) as Json[];
  const items = state.items as Json;
  const [owner,setOwner] = useState(actors[0]?.id || "party");
  const inventory = owner === "party" ? state.party_inventory : state.actors[owner]?.inventory || {};
  const stacks = Object.values(inventory) as Json[];
  const weight = stacks.reduce((sum,s)=>sum + items[s.item_id].weight_lb*s.quantity,0);
  async function add(event:FormEvent<HTMLFormElement>) {event.preventDefault();const f=new FormData(event.currentTarget);await command("add_item",{owner_id:owner,item_id:f.get("item_id"),quantity:Number(f.get("quantity"))});}
  return <><div className="toolbar-row"><div><h2>背包与装备</h2><p>重量按标准负重规则校验</p></div><select value={owner} onChange={e=>setOwner(e.target.value)}><option value="party">队伍共享仓库</option>{actors.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select></div>
    <div className="inventory-summary"><Backpack size={18}/><strong>{weight.toFixed(1)} 磅</strong>{owner!=="party"&&<span>/ {state.actors[owner].abilities.STR*15} 磅</span>}<span>{stacks.length} 个物品栈</span></div>
    <table><thead><tr><th>物品</th><th>类型</th><th>数量</th><th>重量</th><th>装备栏</th><th></th></tr></thead><tbody>{stacks.map(s=>{
      const item=items[s.item_id]; return <tr key={s.id}><td><strong>{item.name}</strong><small>{item.name_en}</small></td><td>{item.kind}</td><td>{s.quantity}</td><td>{(item.weight_lb*s.quantity).toFixed(1)} lb</td><td>{s.equipped_slot||"—"}</td><td className="actions">{owner!=="party"&&item.kind==="weapon"&&!s.equipped_slot&&<button onClick={()=>command("equip_item",{actor_id:owner,stack_id:s.id,slot:"main_hand"})}>装备</button>}{s.equipped_slot&&<button onClick={()=>command("unequip_item",{actor_id:owner,stack_id:s.id})}>卸下</button>}<button className="text-danger" onClick={()=>command("remove_item",{owner_id:owner,stack_id:s.id,quantity:1})}>移除</button></td></tr>})}</tbody></table>
    {!stacks.length&&<Empty title="背包为空"/>}
    <form className="inline-form" onSubmit={add}><select name="item_id">{Object.values(items).map((i:any)=><option value={i.id} key={i.id}>{i.name}</option>)}</select><input name="quantity" type="number" min="1" defaultValue="1"/><button><Plus size={15}/>添加物品</button></form>
  </>;
}

function Shops({state,command}:{state:Json,command:Command}) {
  const shops=Object.values(state.shops) as Json[]; const actors=Object.values(state.actors) as Json[]; const items=Object.values(state.items) as Json[];
  const [shopId,setShopId]=useState(shops[0]?.id||""); const shop=state.shops[shopId]||shops[0];
  useEffect(()=>{if(!shopId&&shops[0])setShopId(shops[0].id)},[shops.length]);
  async function create(e:FormEvent<HTMLFormElement>){e.preventDefault();const formElement=e.currentTarget;const f=new FormData(formElement);const result=await command("create_shop",{name:f.get("name")});if(result)formElement.reset();}
  async function stock(e:FormEvent<HTMLFormElement>){e.preventDefault();const f=new FormData(e.currentTarget);await command("stock_shop",{shop_id:shop.id,item_id:f.get("item_id"),quantity:Number(f.get("quantity"))});}
  return <><div className="toolbar-row"><div><h2>交易</h2><p>所有货币和库存变化原子结算</p></div>{shops.length>0&&<select value={shop?.id} onChange={e=>setShopId(e.target.value)}>{shops.map(s=><option value={s.id} key={s.id}>{s.name}</option>)}</select>}</div>
    {shop?<><div className="shop-strip"><Store size={20}/><strong>{shop.name}</strong><span><Coins size={15}/>{money(shop.wallet_cp)}</span><span>买入 ×{shop.buy_multiplier}</span><span>回收 ×{shop.sell_multiplier}</span></div>
    <table><thead><tr><th>物品</th><th>库存</th><th>角色购买价</th><th>购买</th></tr></thead><tbody>{Object.entries(shop.stock).map(([id,qty]:any)=>{const item=state.items[id];return <tr key={id}><td><strong>{item.name}</strong><small>{item.name_en}</small></td><td>{qty===null?"无限":qty}</td><td>{Math.round(item.price_cp*shop.buy_multiplier)} CP</td><td><div className="buy-buttons">{actors.map(a=><button key={a.id} title={`${a.name} 购买`} onClick={()=>command("buy_item",{shop_id:shop.id,actor_id:a.id,item_id:id,quantity:1})}>{a.name}</button>)}</div></td></tr>})}</tbody></table>
    <form className="inline-form" onSubmit={stock}><select name="item_id">{items.map(i=><option key={i.id} value={i.id}>{i.name}</option>)}</select><input name="quantity" type="number" min="0" defaultValue="1"/><button><Plus size={15}/>设置库存</button></form></>:<Empty title="尚无商店"/>}
    <form className="inline-form" onSubmit={create}><input name="name" placeholder="商店名称" required/><button><Plus size={15}/>创建商店</button></form>
  </>;
}

function Combat({state,command}:{state:Json,command:Command}) {
  const actors=Object.values(state.actors) as Json[]; const encounters=Object.values(state.encounters) as Json[];
  const active=encounters.find(e=>e.status==="active");
  async function create(e:FormEvent<HTMLFormElement>){e.preventDefault();const f=new FormData(e.currentTarget);const party=actors.filter(a=>a.kind==="pc").map(a=>a.id);const enemy=actors.filter(a=>a.kind!=="pc").map(a=>a.id);await command("create_encounter",{name:f.get("name"),sides:{party,enemy}});}
  if(active){const currentId=active.turn_order[active.current_index], current=state.actors[currentId];const targets=actors.filter(a=>a.id!==currentId&&a.hp>0);const weapons=Object.values(current.inventory).filter((s:any)=>s.equipped_slot==="main_hand");const knownSpells=current.spells.map((id:string)=>state.spells[id]).filter(Boolean);return <><div className="combat-head"><div><span>第 {active.round} 轮</span><h2>{active.name}</h2></div><div><small>当前行动者</small><strong>{current.name}</strong></div></div>
    <div className="initiative">{active.turn_order.map((id:string,index:number)=><div className={id===currentId?"active":""} key={id}><span>{active.initiatives[id]}</span><strong>{state.actors[id].name}</strong><small>{state.actors[id].hp} HP</small></div>)}</div>
    <div className="combat-controls"><h3>本回合操作</h3>{current.life_state==="unconscious"?<button onClick={()=>command("combat_death_save",{encounter_id:active.id,actor_id:currentId})}>死亡豁免</button>:<>{targets.map(t=><button key={`atk-${t.id}`} className="attack" disabled={!weapons.length} onClick={()=>command("combat_attack",{encounter_id:active.id,actor_id:currentId,target_id:t.id,stack_id:(weapons[0] as any)?.id})}><Swords size={15}/>攻击 {t.name}</button>)}{knownSpells.flatMap((spell:any)=>targets.slice(0,1).map(t=><button key={`spell-${spell.id}`} onClick={()=>command("combat_cast",{encounter_id:active.id,actor_id:currentId,target_id:t.id,spell_id:spell.id})}>{spell.name} → {t.name}</button>))}</>}<button onClick={()=>command("combat_end_turn",{encounter_id:active.id,actor_id:currentId})}>结束回合</button>{!weapons.length&&current.life_state==="conscious"&&<small>当前角色未装备主手武器</small>}</div>
    <div className="section-head"><div><h2>战斗日志</h2><p>服务端骰子与状态变更</p></div></div><pre className="combat-log">{active.log.slice(-15).map((x:any)=>JSON.stringify(x)).join("\n")}</pre></>}
  const setup=encounters.filter(e=>e.status==="setup");return <><div className="toolbar-row"><div><h2>遭遇</h2><p>自动按 PC 与非 PC 分组创建</p></div></div>{setup.map(e=><div className="setup-row" key={e.id}><Swords size={18}/><div><strong>{e.name}</strong><small>{Object.values(e.sides).flat().length} 名参与者</small></div><button onClick={()=>command("start_encounter",{encounter_id:e.id})}>投先攻并开始</button></div>)}
    <form className="inline-form" onSubmit={create}><input name="name" placeholder="遭遇名称" required/><button disabled={!actors.some(a=>a.kind==="pc")||!actors.some(a=>a.kind!=="pc")}><Plus size={15}/>创建遭遇</button></form></>;
}

function Operations({campaignId,revision,refresh,showError}:any) {
  const [rows,setRows]=useState<Json[]>([]); const load=()=>api<Json[]>(`/api/campaigns/${campaignId}/operations`).then(setRows).catch(showError);
  useEffect(()=>{load()},[campaignId,revision]);
  async function undo(id:string){try{await api(`/api/campaigns/${campaignId}/undo/${id}`,{method:"POST"});await refresh();await load();}catch(e){showError(e)}}
  return <><div className="toolbar-row"><div><h2>操作记录</h2><p>撤销使用补偿事务，不删除历史</p></div></div><table><thead><tr><th>时间</th><th>操作</th><th>来源</th><th>修订</th><th>参数</th><th></th></tr></thead><tbody>{rows.map((r,i)=><tr key={r.id}><td>{new Date(r.created_at).toLocaleString()}</td><td><strong>{r.kind}</strong><small>{r.id}</small></td><td>{r.source}</td><td>{r.before_revision} → {r.after_revision}</td><td className="request-cell">{JSON.stringify(r.request)}</td><td>{i===0&&!r.undone_by&&r.kind!=="undo"&&<button title="撤销" onClick={()=>undo(r.id)}><RotateCcw size={15}/></button>}</td></tr>)}</tbody></table></>;
}
function Empty({title}:{title:string}) {return <div className="empty"><Archive size={26}/><strong>{title}</strong></div>}

createRoot(document.getElementById("root")!).render(<React.StrictMode><App/></React.StrictMode>);
