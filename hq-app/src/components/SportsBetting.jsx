/**
 * Sports Betting — personal bankroll, bet log (your bets + Oracle toggle), edit modals
 * Data: oracle_picks.json, /hq/data (my_bets, my_bankroll)
 * API: POST/PATCH/DELETE /hq/bets, POST /hq/oracle/picks, POST /hq/bankroll
 */
import { useEffect, useState, useCallback, useRef } from 'react'
import { getStoredData, getOracleFile, getOracleResolved, addBet, patchBet, deleteBet, saveOraclePicks, saveOracleResolved, setBankroll, addBankrollTransaction, parseFliffScreenshot, setFliffBalance } from '../api/client.js'
import { fakeAmt } from '../context/DemoContext.jsx'
import { useIsMobile } from '../hooks/useIsMobile.js'

const POLL_MS = 45_000

function fmtDol(v){return '\u0024'+parseFloat(v||0).toFixed(2)}
function fmtPnl(v){const n=parseFloat(v||0);return(n>=0?'+':'-')+'\u0024'+Math.abs(n).toFixed(2)}
function fmtDate(ts){if(!ts)return'—';try{const d=new Date(ts);return['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][d.getMonth()]+' '+d.getDate()}catch{return'—'}}
// Normalize picks that may come from two different schemas:
// New (oracle_bot):  date, odds, stake
// Old (oracle_record): logged_at | game_time | commence, odds_at_log, (no stake)
function pickDate(p){return p.date||p.logged_at||p.game_time||p.commence||''}
function pickOdds(p){return p.odds||p.odds_at_log||''}
function pickStake(p){const s=parseFloat(p.stake||p.stake_usd||0);return s>0?s:null}

function normalizeResult(r){const s=(r||'').toLowerCase();if(s==='w'||s==='win'||s==='won')return'W';if(s==='l'||s==='loss'||s==='lost')return'L';if(s==='p'||s==='push')return'Push';return'Pending'}
function resultPillClass(r){const n=normalizeResult(r);if(n==='W')return'pill-green';if(n==='L')return'pill-red';if(n==='Push')return'pill-blue';return'pill-gold'}

const STARTING_BANKROLL = 334.37
function calcPnl(result, odds, stake){
  const r=normalizeResult(result), o=parseFloat(odds), s=parseFloat(stake)
  if(isNaN(s)||s<=0) return 0
  if(r==='W') return isNaN(o)?0 : o>0 ? +(s*(o/100)).toFixed(2) : +(s*(100/Math.abs(o))).toFixed(2)
  if(r==='L') return +(-s).toFixed(2)
  return 0
}

function calcParlayOdds(legs){
  const valid=legs.filter(l=>l.odds&&!isNaN(parseFloat(l.odds)))
  if(valid.length<2) return ''
  const decimal=valid.reduce((acc,leg)=>{
    const o=parseFloat(leg.odds)
    return acc*(o>0?o/100+1:100/Math.abs(o)+1)
  },1)
  const american=decimal>=2?Math.round((decimal-1)*100):Math.round(-100/(decimal-1))
  return american>0?`+${american}`:`${american}`
}

export default function SportsBetting({ demoMode, isActive=true }) {
  const isMobile = useIsMobile()
  const [oracle, setOracle] = useState(null)
  const [oracleResolved, setOracleResolved] = useState(null)
  const [stored, setStored] = useState(null)
  const [loading,setLoading]= useState(true)
  const [view,   setView]   = useState('my')   // 'my' | 'oracle'
  const [editBet,   setEditBet]   = useState(null)
  const [editPick,  setEditPick]  = useState(null)
  const [addBetOpen,setAddBetOpen]= useState(false)
  const [editBrOpen,setEditBrOpen]= useState(false)
  const [importOpen,setImportOpen]= useState(false)
  const [toast,     setToast]     = useState(null)
  const [myBetsPage, setMyBetsPage] = useState(0)
  const [picksPage,  setPicksPage]  = useState(0)
  const [txFormType, setTxFormType] = useState(null)
  const [txForm, setTxForm] = useState({amount:'',date:new Date().toISOString().split('T')[0],note:''})
  const [txExpanded, setTxExpanded] = useState(false)
  const timer = useRef(null)

  const load=useCallback(async()=>{
    try{
      const [o,r,s]=await Promise.allSettled([getOracleFile(),getOracleResolved(),getStoredData()])
      if(o.status==='fulfilled')setOracle(o.value)
      if(r.status==='fulfilled')setOracleResolved(r.value)
      if(s.status==='fulfilled')setStored(s.value)
    }catch(e){console.error('[SportsBetting]',e)}finally{setLoading(false)}
  },[])

  const recalcBankroll=useCallback(async()=>{
    try{
      const data=await getStoredData()
      const bets=data?.my_bets??data?.bets??[]
      const totalPnl=bets.reduce((sum,b)=>{
        const r=normalizeResult(b.result)
        return(r==='W'||r==='L')?sum+(parseFloat(b.pnl)||0):sum
      },0)
      const startingRef=parseFloat(data?.my_bankroll?.starting??STARTING_BANKROLL)
      await setBankroll({current:+(startingRef+totalPnl).toFixed(2)})
    }catch(e){console.error('[SportsBetting] bankroll recalc',e)}
  },[])

  useEffect(()=>{load().then(()=>recalcBankroll())},[load,recalcBankroll])
  useEffect(()=>{
    if(!isActive){clearInterval(timer.current);return}
    timer.current=setInterval(load,POLL_MS)
    return()=>clearInterval(timer.current)
  },[isActive,load])

  const sortByDate = arr => [...arr].sort((a,b)=>new Date(pickDate(b))-new Date(pickDate(a)))
  const picks  = sortByDate(Array.isArray(oracle) ? oracle : (oracle?.picks ?? []))
  const resolvedPicks = sortByDate(oracleResolved?.picks ?? [])
  const myBets = sortByDate(stored?.my_bets ?? stored?.bets ?? [])
  const myBr   = stored?.my_bankroll ?? {}
  const bankrollTxs = stored?.bankroll_transactions ?? []
  const oracleBr  = parseFloat(oracleResolved?.bankroll ?? oracle?.bankroll ?? 0)
  const _oRes     = picks.filter(p=>normalizeResult(p.result)==='W'||normalizeResult(p.result)==='L')
  const _oWins    = _oRes.filter(p=>normalizeResult(p.result)==='W').length
  const oracleComputedRecord  = _oRes.length ? `${_oWins}-${_oRes.length-_oWins}` : (oracle?.record ?? '—')
  const oracleComputedWinRate = _oRes.length ? `${Math.round(_oWins/_oRes.length*100)}%` : (oracle?.win_rate ?? '—')
  const oraclePnl = picks.reduce((s,p)=>s+(parseFloat(p.pnl)||0),0)
  const resolvedPnl = myBets.reduce((s,b)=>{const r=normalizeResult(b.result);return(r==='W'||r==='L')?s+(parseFloat(b.pnl)||0):s},0)
  const myPnl = myBets.reduce((s,b)=>s+(parseFloat(b.pnl)||0),0)
  const myCurrentBankroll = +((parseFloat(myBr.starting||STARTING_BANKROLL))+resolvedPnl).toFixed(2)
  const myWins= myBets.filter(b=>normalizeResult(b.result)==='W').length
  const myWr  = myBets.length?Math.round(myWins/myBets.length*100):0

  // Straight / Parlay split — personal
  const myResolved    = myBets.filter(b=>{const r=normalizeResult(b.result);return r==='W'||r==='L'})
  const myStraightBets= myResolved.filter(b=>b.type!=='parlay')
  const myParlayBets  = myResolved.filter(b=>b.type==='parlay')
  const myStraightWins= myStraightBets.filter(b=>normalizeResult(b.result)==='W').length
  const myParlayWins  = myParlayBets.filter(b=>normalizeResult(b.result)==='W').length
  const myTotalRecord = myResolved.length?`${myWins}-${myResolved.length-myWins} (${Math.round(myWins/myResolved.length*100)}%)`:'—'
  const myStraightRec = myStraightBets.length?`${myStraightWins}-${myStraightBets.length-myStraightWins} (${Math.round(myStraightWins/myStraightBets.length*100)}%)`:'—'
  const myParlayRec   = myParlayBets.length?`${myParlayWins}-${myParlayBets.length-myParlayWins} (${Math.round(myParlayWins/myParlayBets.length*100)}%)`:'—'

  // Straight / Parlay split — Oracle
  const _oStraights    = _oRes.filter(p=>p.type!=='parlay')
  const _oParlays      = _oRes.filter(p=>p.type==='parlay')
  const _oStraightWins = _oStraights.filter(p=>normalizeResult(p.result)==='W').length
  const _oParlayWins   = _oParlays.filter(p=>normalizeResult(p.result)==='W').length
  const oracleTotalRec    = _oRes.length?`${_oWins}-${_oRes.length-_oWins} (${Math.round(_oWins/_oRes.length*100)}%)`:(oracle?.record??'—')
  const oracleStraightRec = _oStraights.length?`${_oStraightWins}-${_oStraights.length-_oStraightWins} (${Math.round(_oStraightWins/_oStraights.length*100)}%)`:'—'
  const oracleParlayRec   = _oParlays.length?`${_oParlayWins}-${_oParlays.length-_oParlayWins} (${Math.round(_oParlayWins/_oParlays.length*100)}%)`:'—'

  // Demo fake values
  const D = demoMode
  const dBankroll  = fakeAmt('sb.br',    400, 1600)
  const dMyPnl     = fakeAmt('sb.mypnl',  50,  600)
  const dOracleBr  = fakeAmt('sb.obr',   600, 1900)
  const dOraclePnl = fakeAmt('sb.opnl',   80,  800)

  // Hero layout
  const heroLayout = isMobile ? '1fr' : '1fr 320px'

  return(
    <div>
      <h1 className="page-title">Sports Betting</h1>

      {/* ── Personal bankroll hero ────────────────────────────────────── */}
      <div className="glass" style={{border:'1px solid rgba(201,168,76,0.2)',position:'relative',overflow:'hidden',marginBottom:16}}>
        <div style={{position:'absolute',bottom:0,left:0,right:0,height:2,background:'linear-gradient(90deg,var(--gold),transparent)'}}/>
        <div style={{display:'grid',gridTemplateColumns: heroLayout,gap:0,overflow:'hidden'}}>
          <div style={{padding:'22px 24px'}}>
            <div style={{display:'flex',alignItems:'center',gap:10,marginBottom:4}}>
              <span style={{fontFamily:'"Playfair Display",serif',fontSize: isMobile ? 20 : 24,color:'var(--text-primary)'}}>Personal Bankroll</span>
              {!D && <button className="edit-btn" onClick={()=>setEditBrOpen(true)}>✎ Edit</button>}
            </div>
            <div style={{fontFamily:'"Playfair Display",serif',fontSize: isMobile ? 32 : 40,color:'var(--gold)',marginBottom:16}}>
              {D ? fmtDol(dBankroll) : fmtDol(myCurrentBankroll)}
            </div>
            <div style={{display:'grid',gridTemplateColumns:'repeat(3,1fr)',gap:16}}>
              <BrStat label="Win Rate"     val={myWr+'%'}                                                     />
              <BrStat label="Total P&L"    val={D ? fmtPnl(dMyPnl)     : fmtPnl(myPnl)}     color={(D?dMyPnl:myPnl)>=0?'var(--green)':'var(--red)'}/>
              <BrStat label="Total"        val={myTotalRecord}                                                 />
              <BrStat label="Total Bets"   val={myBets.length}                                                 />
              <BrStat label="Straights"    val={myStraightRec}                                                 />
              <BrStat label="Parlays"      val={myParlayRec}                                                   />
              <BrStat label="ROI"          val={myBr.roi??'—'}                                                 />
              <BrStat label="Avg Stake"    val={D ? fmtDol(fakeAmt('sb.stake',8,35)) : (myBets.length?fmtDol(myBets.reduce((s,b)=>s+(parseFloat(b.stake)||0),0)/myBets.length):'—')}/>
            </div>
          </div>
          {/* Transactions column — hidden on mobile */}
          {!isMobile && (
            <div style={{borderLeft:'1px solid rgba(255,255,255,0.05)',padding:'22px 18px',display:'flex',flexDirection:'column'}}>
              <div style={{fontSize:8,letterSpacing:3,textTransform:'uppercase',color:'var(--text-muted)',marginBottom:10}}>Transactions</div>
              {!D && !txFormType && (
                <div style={{display:'flex',gap:6,marginBottom:12}}>
                  <button className="edit-btn" style={{color:'var(--green)',borderColor:'rgba(74,222,128,0.25)'}} onClick={()=>{setTxForm({amount:'',date:new Date().toISOString().split('T')[0],note:''});setTxFormType('deposit')}}>+ Deposit</button>
                  <button className="edit-btn" style={{color:'var(--red)',borderColor:'rgba(248,113,113,0.25)'}} onClick={()=>{setTxForm({amount:'',date:new Date().toISOString().split('T')[0],note:''});setTxFormType('withdraw')}}>− Withdraw</button>
                </div>
              )}
              {txFormType && (
                <div style={{marginBottom:12,padding:'10px',background:'rgba(255,255,255,0.03)',borderRadius:8,border:'1px solid rgba(255,255,255,0.07)'}}>
                  <div style={{fontSize:9,letterSpacing:2,textTransform:'uppercase',color:txFormType==='deposit'?'var(--green)':'var(--red)',marginBottom:8,fontWeight:600}}>{txFormType==='deposit'?'+ Deposit':'− Withdraw'}</div>
                  <div style={{display:'flex',flexDirection:'column',gap:5}}>
                    <input type="number" placeholder="Amount ($)" value={txForm.amount} onChange={e=>setTxForm(f=>({...f,amount:e.target.value}))} style={{fontSize:11,padding:'5px 8px',borderRadius:5,border:'1px solid rgba(255,255,255,0.1)',background:'rgba(255,255,255,0.05)',color:'var(--text-primary)',width:'100%',outline:'none'}}/>
                    <input type="date" value={txForm.date} onChange={e=>setTxForm(f=>({...f,date:e.target.value}))} style={{fontSize:11,padding:'5px 8px',borderRadius:5,border:'1px solid rgba(255,255,255,0.1)',background:'rgba(255,255,255,0.05)',color:'var(--text-primary)',width:'100%',outline:'none'}}/>
                    <input placeholder="Note (optional)" value={txForm.note} onChange={e=>setTxForm(f=>({...f,note:e.target.value}))} style={{fontSize:11,padding:'5px 8px',borderRadius:5,border:'1px solid rgba(255,255,255,0.1)',background:'rgba(255,255,255,0.05)',color:'var(--text-primary)',width:'100%',outline:'none'}}/>
                    <div style={{display:'flex',gap:5,justifyContent:'flex-end',marginTop:2}}>
                      <button className="edit-btn" onClick={()=>setTxFormType(null)}>Cancel</button>
                      <button className="edit-btn" style={{color:txFormType==='deposit'?'var(--green)':'var(--red)',borderColor:txFormType==='deposit'?'rgba(74,222,128,0.25)':'rgba(248,113,113,0.25)'}} onClick={async()=>{
                        const amt=parseFloat(txForm.amount)
                        if(!amt||amt<=0) return
                        await addBankrollTransaction({type:txFormType,amount:amt,date:txForm.date,note:txForm.note})
                        setTxFormType(null)
                        load()
                      }}>Save</button>
                    </div>
                  </div>
                </div>
              )}
              {bankrollTxs.length===0
                ? <div style={{fontSize:11,color:'var(--text-muted)',fontStyle:'italic'}}>No transactions yet.</div>
                : <>
                    {(txExpanded?bankrollTxs:bankrollTxs.slice(0,5)).map((tx,i)=>(
                      <div key={tx.id??i} style={{display:'grid',gridTemplateColumns:'52px 42px 62px 1fr',gap:4,padding:'5px 0',borderBottom:'1px solid rgba(255,255,255,0.04)',fontSize:10,alignItems:'center'}}>
                        <span style={{color:'var(--text-muted)',fontFamily:'"IBM Plex Mono",monospace',fontSize:9}}>{tx.date||'—'}</span>
                        <span style={{color:tx.type==='deposit'?'var(--green)':'var(--red)',textTransform:'uppercase',fontWeight:700,fontSize:8,letterSpacing:1}}>{tx.type==='deposit'?'DEP':'WDR'}</span>
                        <span style={{fontFamily:'"IBM Plex Mono",monospace',color:tx.type==='deposit'?'var(--green)':'var(--red)',fontSize:10}}>{tx.type==='deposit'?'+':'-'}${parseFloat(tx.amount||0).toFixed(2)}</span>
                        <span style={{color:'var(--text-muted)',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap',fontSize:10}}>{tx.note||''}</span>
                      </div>
                    ))}
                    {bankrollTxs.length>5&&(
                      <button className="edit-btn" style={{marginTop:6,width:'100%',textAlign:'center'}} onClick={()=>setTxExpanded(x=>!x)}>
                        {txExpanded?'Show less':'View all ('+bankrollTxs.length+')'}
                      </button>
                    )}
                  </>
              }
            </div>
          )}
        </div>
      </div>

      {/* ── Bet log ──────────────────────────────────────────────────── */}
      <div className="section-head"><div className="section-line"/><h3>Bet History</h3><div className="section-line"/>
        {!D && <div style={{display:'flex',gap:6,flexShrink:0}}>
          <button className="edit-btn ml-2 shrink-0" onClick={()=>setAddBetOpen(true)}>+ Log Bet</button>
          <button className="edit-btn" style={{color:'var(--gold)',borderColor:'rgba(201,168,76,0.35)',background:'rgba(201,168,76,0.06)'}} onClick={()=>setImportOpen(true)}>📷 Import Screenshot</button>
        </div>}
      </div>

      {/* Toggle */}
      <div style={{display:'flex',gap:8,marginBottom:12}}>
        <button onClick={()=>setView('my')} style={{padding:'7px 16px',borderRadius:6,cursor:'pointer',fontSize:11,fontWeight:500,background:view==='my'?'rgba(201,168,76,0.1)':'rgba(255,255,255,0.02)',color:view==='my'?'var(--gold)':'var(--text-muted)',border:view==='my'?'1px solid rgba(201,168,76,0.25)':'1px solid rgba(255,255,255,0.07)',transition:'all .15s'}}>Your Bets</button>
        <button onClick={()=>setView('oracle')} style={{padding:'7px 16px',borderRadius:6,cursor:'pointer',fontSize:11,fontWeight:500,display:'flex',alignItems:'center',gap:7,background:view==='oracle'?'rgba(167,139,250,0.1)':'rgba(255,255,255,0.02)',color:view==='oracle'?'var(--purple)':'var(--text-muted)',border:view==='oracle'?'1px solid rgba(167,139,250,0.25)':'1px solid rgba(255,255,255,0.07)',transition:'all .15s'}}>
          <img src="/agent_oracle.jpg" style={{width:16,height:16,borderRadius:'50%',objectFit:'cover'}} alt="Oracle"/>
          Oracle Picks
        </button>
      </div>

      {view==='my'
        ?(
          loading?<SkeletonTable/>:!myBets.length
            ?<div className="glass" style={{padding:'14px 18px',fontSize:11,color:'var(--text-muted)',fontStyle:'italic'}}>No bets logged yet.</div>
            :(()=>{
              const PAGE_SIZE=15
              const totalPages=Math.max(1,Math.ceil(myBets.length/PAGE_SIZE))
              const safePage=Math.min(myBetsPage,totalPages-1)
              const pageStart=safePage*PAGE_SIZE
              const pageBets=myBets.slice(pageStart,pageStart+PAGE_SIZE)
              return(
                <div className="glass" style={{overflowX:'auto'}}>
                  <div style={{padding:'8px 16px 4px',display:'grid',gridTemplateColumns:'75px 1fr 60px 70px 70px 70px 110px',gap:6,fontSize:8,letterSpacing:2,textTransform:'uppercase',color:'var(--text-muted)',borderBottom:'1px solid rgba(255,255,255,0.06)',minWidth:500}}>
                    {['Date','Pick','Odds','Stake','Result','P&L',''].map(h=><span key={h}>{h}</span>)}
                  </div>
                  {pageBets.map((b,i)=>{
                    const absIdx=pageStart+i
                    const pnl=parseFloat(b.pnl||0)
                    const dPnl = D ? fakeAmt('sb.bet.'+absIdx, -80, 180) : pnl
                    const dStake = D ? fakeAmt('sb.stk.'+absIdx, 8, 40) : (b.stake||0)
                    const betType=(b.type==='parlay'?'PARLAY':'STRAIGHT')
                    const betSrc=(b.source||'Manual')
                    return(
                      <div key={b.id??absIdx} style={{padding:'8px 16px',display:'grid',gridTemplateColumns:'75px 1fr 60px 70px 70px 70px 110px',gap:6,fontSize:11,borderBottom:'1px solid rgba(255,255,255,0.025)',alignItems:'center',minWidth:500}}>
                        <span style={{fontFamily:'"IBM Plex Mono",monospace',fontSize:10,color:'var(--text-muted)'}}>{b.date||'—'}</span>
                        <div>
                          <div style={{color:'var(--text-dim)',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{b.pick||b.bet||'—'}</div>
                          <div style={{display:'flex',gap:4,marginTop:2}}>
                            <span style={{fontSize:8,padding:'1px 5px',borderRadius:3,background:b.type==='parlay'?'rgba(167,139,250,0.15)':'rgba(201,168,76,0.1)',color:b.type==='parlay'?'var(--purple)':'var(--gold)',border:b.type==='parlay'?'1px solid rgba(167,139,250,0.3)':'1px solid rgba(201,168,76,0.2)',letterSpacing:1,fontWeight:700}}>{betType}</span>
                            {betSrc==='Fliff'&&<span style={{fontSize:8,padding:'1px 5px',borderRadius:3,background:'rgba(74,222,128,0.1)',color:'var(--green)',border:'1px solid rgba(74,222,128,0.2)',letterSpacing:1,fontWeight:700}}>FLIFF</span>}
                          </div>
                        </div>
                        <span style={{fontFamily:'"IBM Plex Mono",monospace',fontSize:10}}>{b.odds||'—'}</span>
                        <span style={{fontFamily:'"IBM Plex Mono",monospace',fontSize:10}}>{fmtDol(dStake)}</span>
                        <span className={`pill ${resultPillClass(b.result)}`}>{normalizeResult(b.result)}</span>
                        <span style={{fontFamily:'"IBM Plex Mono",monospace',fontSize:11,fontWeight:600,color:dPnl>=0?'var(--green)':'var(--red)'}}>{fmtPnl(dPnl)}</span>
                        <div style={{display:'flex',gap:4}}>
                          {!D && <button className="edit-btn" onClick={()=>setEditBet({bet:b,idx:absIdx})}>✎</button>}
                          {!D && <button className="edit-btn" onClick={async()=>{if(confirm('Delete bet?')){await deleteBet(b.id);load()}}}>✕</button>}
                        </div>
                      </div>
                    )
                  })}
                  <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',padding:'10px 16px',borderTop:'1px solid rgba(255,255,255,0.06)'}}>
                    <span style={{fontSize:10,color:'var(--text-muted)',fontFamily:'"IBM Plex Mono",monospace'}}>{myBets.length} bets total</span>
                    <div style={{display:'flex',alignItems:'center',gap:10}}>
                      <button className="edit-btn" onClick={()=>setMyBetsPage(p=>Math.max(0,p-1))} disabled={safePage===0} style={{opacity:safePage===0?0.35:1}}>← Previous</button>
                      <span style={{fontSize:10,color:'var(--text-muted)',fontFamily:'"IBM Plex Mono",monospace'}}>Page {safePage+1} of {totalPages}</span>
                      <button className="edit-btn" onClick={()=>setMyBetsPage(p=>Math.min(totalPages-1,p+1))} disabled={safePage===totalPages-1} style={{opacity:safePage===totalPages-1?0.35:1}}>Next →</button>
                    </div>
                  </div>
                </div>
              )
            })()
        ):(
          /* Oracle picks panel */
          <div>
            {/* Oracle hero stats */}
            <div className="glass" style={{border:'1px solid rgba(167,139,250,0.2)',display:'grid',gridTemplateColumns: isMobile ? '1fr' : '160px 1fr',overflow:'hidden',marginBottom:12}}>
              {!isMobile && (
                <div style={{position:'relative',background:'#080e1e',overflow:'hidden'}}>
                  <img src="/agent_oracle.jpg" alt="Oracle" style={{width:'100%',height:'100%',objectFit:'cover',objectPosition:'top',display:'block',minHeight:140}}/>
                  <div style={{position:'absolute',inset:0,background:'linear-gradient(90deg,transparent 50%,rgba(7,12,26,0.98) 100%)'}}/>
                </div>
              )}
              <div style={{padding:'18px 22px'}}>
                <span style={{fontSize:8,padding:'2px 8px',borderRadius:20,background:'rgba(167,139,250,0.12)',color:'var(--purple)',border:'1px solid rgba(167,139,250,0.3)',display:'inline-block',letterSpacing:2,textTransform:'uppercase',marginBottom:10}}>Sports Analyst</span>
                <div style={{fontFamily:'"Playfair Display",serif',fontSize:20,color:'var(--text-primary)',marginBottom:12}}>Oracle</div>
                <div style={{display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:12}}>
                  <BrStat label="Bankroll"  val={D ? fmtDol(dOracleBr) : fmtDol(oracleBr)} color="var(--purple)"/>
                  <BrStat label="Total"     val={oracleTotalRec}/>
                  <BrStat label="Win Rate"  val={oracleComputedWinRate} color="var(--gold)"/>
                  <BrStat label="Total P&L" val={D ? fmtPnl(dOraclePnl) : fmtPnl(oraclePnl)} color={(D?dOraclePnl:oraclePnl)>=0?'var(--green)':'var(--red)'}/>
                  <BrStat label="Straights" val={oracleStraightRec}/>
                  <BrStat label="Parlays"   val={oracleParlayRec}/>
                </div>
              </div>
            </div>
            {/* Oracle picks table */}
            {loading?<SkeletonTable/>:!picks.length
              ?<div className="glass" style={{padding:'14px 18px',fontSize:11,color:'var(--text-muted)',fontStyle:'italic'}}>No Oracle picks.</div>
              :(()=>{
                const PAGE_SIZE=15
                const totalPages=Math.max(1,Math.ceil(picks.length/PAGE_SIZE))
                const safePage=Math.min(picksPage,totalPages-1)
                const pageStart=safePage*PAGE_SIZE
                const pagePicks=picks.slice(pageStart,pageStart+PAGE_SIZE)
                return(
                  <div className="glass" style={{overflowX:'auto'}}>
                    <div style={{padding:'8px 16px 4px',display:'grid',gridTemplateColumns:'60px 1fr 70px 60px 70px 70px 60px',gap:6,fontSize:8,letterSpacing:2,textTransform:'uppercase',color:'var(--text-muted)',borderBottom:'1px solid rgba(255,255,255,0.06)',minWidth:480}}>
                      {['Date','Pick','Type','Odds','Stake','P&L',''].map(h=><span key={h}>{h}</span>)}
                    </div>
                    {pagePicks.map((p,i)=>{
                      const absIdx=pageStart+i
                      const pnl=parseFloat(p.pnl||0)
                      const dPnl   = D ? fakeAmt('sb.pick.'+absIdx, -60, 150) : pnl
                      const rawStake = pickStake(p)
                      const dStake = D ? fakeAmt('sb.pstk.'+absIdx, 10, 50) : rawStake
                      const isParlay = p.type==='parlay'
                      const bt = p.bet_type || (isParlay ? 'PARLAY' : 'ML')
                      const btColor = {ML:'pill-gold',SPREAD:'pill-blue',TOTAL:'pill-green',TEAM_TOTAL:'pill-blue',PARLAY:'pill-purple'}[bt]||'pill-blue'
                      const sportLabel = isParlay ? '🎰' : (p.sport||'—')
                      return(
                        <div key={p.id??absIdx} style={{padding:'8px 16px',display:'grid',gridTemplateColumns:'60px 1fr 70px 60px 70px 70px 60px',gap:6,fontSize:11,borderBottom:'1px solid rgba(255,255,255,0.025)',alignItems:'center',minWidth:480,background:isParlay?'rgba(167,139,250,0.04)':''}}>
                          <span style={{fontFamily:'"IBM Plex Mono",monospace',fontSize:10,color:'var(--text-muted)'}}>{fmtDate(pickDate(p))}</span>
                          <div style={{color:'var(--text-dim)',overflow:'hidden',minWidth:0}}>
                            <div style={{overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{p.pick||'—'}</div>
                            {isParlay && Array.isArray(p.leg_labels) && p.leg_labels.length > 0 && (
                              <div style={{marginTop:3,fontSize:9,color:'var(--text-muted)',lineHeight:1.45,fontFamily:'"IBM Plex Mono",monospace'}}>
                                {p.leg_labels.map((lbl,li)=>(
                                  <div key={li} style={{overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>• {lbl}</div>
                                ))}
                              </div>
                            )}
                          </div>
                          <span className={`pill ${btColor}`} style={{fontSize:8}}>{bt}</span>
                          <span style={{fontFamily:'"IBM Plex Mono",monospace',color:'var(--gold)'}}>{pickOdds(p)||'—'}</span>
                          <span style={{fontFamily:'"IBM Plex Mono",monospace'}}>{D&&dStake?fmtDol(dStake):rawStake?fmtDol(rawStake):'—'}</span>
                          <span style={{fontFamily:'"IBM Plex Mono",monospace',fontWeight:600,color:dPnl>=0?'var(--green)':'var(--red)'}}>{fmtPnl(dPnl)}</span>
                          <div style={{display:'flex',gap:3,alignItems:'center'}}>
                            <span className={`pill ${resultPillClass(p.result)}`}>{normalizeResult(p.result)}</span>
                            {!D && <button className="edit-btn" onClick={()=>setEditPick({pick:p,idx:absIdx})}>✎</button>}
                          </div>
                        </div>
                      )
                    })}
                    <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',padding:'10px 16px',borderTop:'1px solid rgba(255,255,255,0.06)'}}>
                      <span style={{fontSize:10,color:'var(--text-muted)',fontFamily:'"IBM Plex Mono",monospace'}}>{picks.length} picks total</span>
                      <div style={{display:'flex',alignItems:'center',gap:10}}>
                        <button className="edit-btn" onClick={()=>setPicksPage(p=>Math.max(0,p-1))} disabled={safePage===0} style={{opacity:safePage===0?0.35:1}}>← Previous</button>
                        <span style={{fontSize:10,color:'var(--text-muted)',fontFamily:'"IBM Plex Mono",monospace'}}>Page {safePage+1} of {totalPages}</span>
                        <button className="edit-btn" onClick={()=>setPicksPage(p=>Math.min(totalPages-1,p+1))} disabled={safePage===totalPages-1} style={{opacity:safePage===totalPages-1?0.35:1}}>Next →</button>
                      </div>
                    </div>
                  </div>
                )
              })()
            }
          </div>
        )
      }

      {/* ── Modals ───────────────────────────────────────────────────── */}
      {importOpen&&<FliffImportModal onClose={()=>setImportOpen(false)} onImported={async(count)=>{setImportOpen(false);await recalcBankroll();load();setToast(`${count} bet${count!==1?'s':''} imported successfully`);setTimeout(()=>setToast(null),3500)}}/>}
      {toast&&<Toast msg={toast}/>}
      {addBetOpen&&<AddBetModal onSave={async b=>{const pnl=calcPnl(b.result,b.odds,b.stake);await addBet({...b,id:Date.now(),pnl});setAddBetOpen(false);await recalcBankroll();load()}} onClose={()=>setAddBetOpen(false)}/>}
      {editBet&&<BetEditModal bet={editBet.bet} onSave={async p=>{const pnl=calcPnl(p.result,editBet.bet.odds,editBet.bet.stake);await patchBet(editBet.bet.id,{...p,pnl});setEditBet(null);await recalcBankroll();load()}} onClose={()=>setEditBet(null)}/>}
      {editPick&&<PickEditModal pick={editPick.pick} onSave={async p=>{
        const np=[...picks]
        np[editPick.idx]={...picks[editPick.idx],...p}
        const updatedPicks=np.reverse()
        const totalPnl=+updatedPicks.reduce((s,pk)=>s+(parseFloat(pk.pnl)||0),0).toFixed(2)
        const rPks=updatedPicks.filter(pk=>normalizeResult(pk.result)==='W'||normalizeResult(pk.result)==='L')
        const rWins=rPks.filter(pk=>normalizeResult(pk.result)==='W').length
        const newBankroll=+(500+totalPnl).toFixed(2)
        await saveOraclePicks({
          ...(Array.isArray(oracle)?{}:oracle||{}),
          balance:newBankroll,
          record:`${rWins}W - ${rPks.length-rWins}L`,
          win_rate:rPks.length?`${Math.round(rWins/rPks.length*100)}%`:'0%',
          total_pnl:totalPnl,
          last_updated:new Date().toISOString(),
          picks:updatedPicks,
        })
        await saveOracleResolved({
          ...(oracleResolved||{}),
          picks:updatedPicks,
          total_pnl:totalPnl,
          bankroll:newBankroll,
          record:`${rWins}-${rPks.length-rWins}`,
          win_rate:rPks.length?`${Math.round(rWins/rPks.length*100)}%`:'0%',
          updated:new Date().toISOString(),
        })
        setEditPick(null);load()
      }} onClose={()=>setEditPick(null)}/>}
      {editBrOpen&&<BankrollEditModal br={myBr} onSave={async p=>{await setBankroll(p);setEditBrOpen(false);load()}} onClose={()=>setEditBrOpen(false)}/>}
    </div>
  )
}

function BrStat({label,val,color='var(--text-primary)'}){
  return(
    <div>
      <div style={{fontSize:8,letterSpacing:2,textTransform:'uppercase',color:'var(--text-muted)',marginBottom:3}}>{label}</div>
      <div style={{fontFamily:'"IBM Plex Mono",monospace',fontSize:13,color}}>{val}</div>
    </div>
  )
}

function Modal({title,onClose,children}){
  return(
    <div className="modal-overlay open" onClick={e=>e.target===e.currentTarget&&onClose()}>
      <div className="modal-box">
        <button onClick={onClose} style={{position:'absolute',top:14,right:16,fontSize:16,background:'none',border:'none',color:'var(--text-muted)',cursor:'pointer'}}>✕</button>
        <h2 className="modal-title text-primary">{title}</h2>
        {children}
        </div>
    </div>
  )
}
function ModalBtns({onClose,onSave}){return<div style={{display:'flex',gap:8,justifyContent:'flex-end',marginTop:18}}><button className="mbtn cancel" onClick={onClose}>Cancel</button><button className="mbtn save" onClick={onSave}>Save</button></div>}

function AddBetModal({onSave,onClose}){
  const [f,setF]=useState({pick:'',sport:'',odds:'',stake:'',result:'pending',date:new Date().toISOString().split('T')[0],type:'straight'})
  const [legs,setLegs]=useState([{pick:'',odds:''},{pick:'',odds:''}])
  const s=(k,v)=>setF(x=>({...x,[k]:v}))
  const isParlay=f.type==='parlay'
  const parlayOdds=calcParlayOdds(legs)

  const addLeg=()=>{ if(legs.length<4) setLegs(l=>[...l,{pick:'',odds:''}]) }
  const removeLeg=idx=>{ if(legs.length>2) setLegs(l=>l.filter((_,i)=>i!==idx)) }
  const setLeg=(idx,k,v)=>setLegs(l=>l.map((leg,i)=>i===idx?{...leg,[k]:v}:leg))

  const handleSave=()=>{
    const payload={...f}
    if(isParlay){
      payload.pick=payload.pick||legs.map(l=>l.pick).filter(Boolean).join(' + ')
      payload.odds=parlayOdds
      payload.legs=legs
    }
    onSave(payload)
  }

  return(<Modal title="Log Bet" onClose={onClose}>
    <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:10,marginBottom:10}}>
      <div className="mf"><label>Bet Type</label>
        <select value={f.type} onChange={e=>s('type',e.target.value)}>
          <option value="straight">Straight</option>
          <option value="parlay">Parlay</option>
        </select>
      </div>
      <div className="mf"><label>Date</label><input type="date" value={f.date} onChange={e=>s('date',e.target.value)}/></div>
    </div>

    {isParlay?(
      <div>
        <div style={{fontSize:8,letterSpacing:2,textTransform:'uppercase',color:'var(--text-muted)',marginBottom:8}}>Legs (2–4)</div>
        {legs.map((leg,i)=>(
          <div key={i} style={{display:'grid',gridTemplateColumns:'1fr 80px 24px',gap:6,marginBottom:6,alignItems:'center'}}>
            <input placeholder={`Leg ${i+1} pick`} value={leg.pick} onChange={e=>setLeg(i,'pick',e.target.value)} style={{fontSize:11,color:'var(--text-primary)',background:'rgba(255,255,255,0.04)',border:'1px solid rgba(255,255,255,0.08)',padding:'6px 10px',borderRadius:6,outline:'none',width:'100%'}}/>
            <input placeholder="Odds" value={leg.odds} onChange={e=>setLeg(i,'odds',e.target.value)} style={{fontSize:11,color:'var(--text-primary)',background:'rgba(255,255,255,0.04)',border:'1px solid rgba(255,255,255,0.08)',padding:'6px 10px',borderRadius:6,outline:'none'}}/>
            <button className="edit-btn" onClick={()=>removeLeg(i)} disabled={legs.length<=2} style={{opacity:legs.length<=2?0.3:1,fontSize:11,padding:'2px 6px'}}>✕</button>
          </div>
        ))}
        <div style={{display:'flex',alignItems:'center',gap:12,marginBottom:10}}>
          {legs.length<4&&<button className="edit-btn" onClick={addLeg} style={{fontSize:10}}>+ Add Leg</button>}
          {parlayOdds&&<span style={{fontFamily:'"IBM Plex Mono",monospace',fontSize:11,color:'var(--gold)'}}>Combined: {parlayOdds}</span>}
        </div>
        <div className="mf"><label>Parlay Name (optional)</label><input value={f.pick} onChange={e=>s('pick',e.target.value)} placeholder="e.g. 3-leg NBA parlay"/></div>
      </div>
    ):(
      <div>
        <div className="mf"><label>Pick / Team</label><input value={f.pick} onChange={e=>s('pick',e.target.value)} placeholder="e.g. Lakers -4.5"/></div>
        <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:10}}>
          <div className="mf"><label>Sport</label><input value={f.sport} onChange={e=>s('sport',e.target.value)} placeholder="NBA"/></div>
          <div className="mf"><label>Odds</label><input value={f.odds} onChange={e=>s('odds',e.target.value)} placeholder="-110"/></div>
        </div>
      </div>
    )}

    <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:10}}>
      <div className="mf"><label>Stake ($)</label><input type="number" step="any" value={f.stake} onChange={e=>s('stake',e.target.value)}/></div>
      <div className="mf"><label>Result</label><select value={f.result} onChange={e=>s('result',e.target.value)}><option value="pending">Pending</option><option value="W">Win</option><option value="L">Loss</option><option value="push">Push</option></select></div>
    </div>
    <ModalBtns onClose={onClose} onSave={handleSave}/>
  </Modal>)
}

function BetEditModal({bet,onSave,onClose}){
  const [f,setF]=useState({result:bet?.result||'pending'})
  const s=(k,v)=>setF(x=>({...x,[k]:v}))
  return(<Modal title="Resolve Bet" onClose={onClose}>
    <div className="mf"><label>Pick</label><div style={{fontSize:12,color:'var(--text-dim)',padding:'6px 0'}}>{bet?.pick||bet?.bet}</div></div>
    <div className="mf"><label>Result</label><select value={f.result} onChange={e=>s('result',e.target.value)}><option value="pending">Pending</option><option value="W">Win</option><option value="L">Loss</option><option value="push">Push</option></select></div>
    <ModalBtns onClose={onClose} onSave={()=>onSave(f)}/>
  </Modal>)
}

function PickEditModal({pick,onSave,onClose}){
  const [f,setF]=useState({result:pick?.result||'pending',pnl:pick?.pnl||''})
  const s=(k,v)=>setF(x=>({...x,[k]:v}))
  return(<Modal title="Edit Oracle Pick" onClose={onClose}>
    <div className="mf"><label>Pick</label><div style={{fontSize:12,color:'var(--text-dim)',padding:'6px 0'}}>{pick?.pick}</div></div>
    <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:10}}>
      <div className="mf"><label>Result</label><select value={f.result} onChange={e=>s('result',e.target.value)}><option value="pending">Pending</option><option value="W">Win</option><option value="L">Loss</option><option value="push">Push</option></select></div>
      <div className="mf"><label>P&L ($)</label><input type="number" step="any" value={f.pnl} onChange={e=>s('pnl',e.target.value)}/></div>
    </div>
    <ModalBtns onClose={onClose} onSave={()=>onSave(f)}/>
  </Modal>)
}

function BankrollEditModal({br,onSave,onClose}){
  const [f,setF]=useState({starting:br?.starting||br?.current||br?.bankroll||''})
  const s=(k,v)=>setF(x=>({...x,[k]:v}))
  return(<Modal title="Edit Bankroll" onClose={onClose}>
    <div className="mf"><label>Starting Bankroll ($)</label><input type="number" step="any" value={f.starting} onChange={e=>s('starting',e.target.value)}/></div>
    <ModalBtns onClose={onClose} onSave={()=>onSave({starting:parseFloat(f.starting),current:parseFloat(f.starting)})}/>
  </Modal>)
}

function Toast({msg}){
  return(
    <div style={{position:'fixed',bottom:32,left:'50%',transform:'translateX(-50%)',background:'rgba(20,26,40,0.97)',border:'1px solid rgba(74,222,128,0.4)',color:'var(--green)',padding:'10px 22px',borderRadius:10,fontSize:13,fontWeight:600,zIndex:9999,boxShadow:'0 4px 24px rgba(0,0,0,0.4)',whiteSpace:'nowrap'}}>
      ✓ {msg}
    </div>
  )
}

function FliffImportModal({onClose,onImported}){
  const [stage,setStage]=useState('upload')
  const [file,setFile]=useState(null)
  const [dragOver,setDragOver]=useState(false)
  const [loading,setLoading]=useState(false)
  const [error,setError]=useState(null)
  const [parsedData,setParsedData]=useState(null)
  const [reviewBets,setReviewBets]=useState([])
  const [updateBalance,setUpdateBalance]=useState(false)
  const [saving,setSaving]=useState(false)
  const fileRef=useRef(null)

  const handleFile=f=>{
    if(!f)return
    setFile(f)
    setError(null)
  }

  const handleParse=async()=>{
    if(!file)return
    setLoading(true)
    setError(null)
    try{
      const fd=new FormData()
      fd.append('image',file)
      const res=await parseFliffScreenshot(fd)
      if(!res.ok)throw new Error(res.error||'Parse failed')
      const data=res.data
      const bets=(data.bets||[]).map((b,i)=>({
        ...b,_id:i,included:true,
        date:b.date||new Date().toISOString().split('T')[0]
      }))
      setParsedData(data)
      setReviewBets(bets)
      setUpdateBalance((data.fliff_balance||0)>0)
      setStage('review')
    }catch(e){
      setError(e.message)
    }finally{
      setLoading(false)
    }
  }

  const handleConfirm=async()=>{
    setSaving(true)
    try{
      const toImport=reviewBets.filter(b=>b.included)
      for(const b of toImport){
        const r=b.result==='win'?'W':b.result==='loss'?'L':'pending'
        const pnl=r==='W'?(parseFloat(b.profit)||0):r==='L'?-(parseFloat(b.stake)||0):0
        const pickLabel=b.type==='parlay'
          ?`${(b.legs||[]).length} Leg Parlay`
          :(b.legs?.[0]?.pick||b.sport||'Straight Bet')
        await addBet({
          id:Date.now()+Math.random()*1000,
          date:b.date,
          pick:pickLabel,
          type:b.type||'straight',
          sport:b.sport||'',
          odds:b.odds||'',
          stake:parseFloat(b.stake)||0,
          payout:parseFloat(b.payout)||0,
          pnl,
          result:r,
          source:'Fliff',
          legs:(b.legs||[]),
        })
      }
      if(updateBalance&&(parsedData?.fliff_balance||0)>0){
        await setFliffBalance(parsedData.fliff_balance)
      }
      onImported(toImport.length)
    }catch(e){
      setError(e.message)
    }finally{
      setSaving(false)
    }
  }

  const toggleBet=id=>setReviewBets(bs=>bs.map(b=>b._id===id?{...b,included:!b.included}:b))
  const updateDate=(id,d)=>setReviewBets(bs=>bs.map(b=>b._id===id?{...b,date:d}:b))

  const inp={fontSize:11,padding:'5px 8px',borderRadius:5,border:'1px solid rgba(255,255,255,0.1)',background:'rgba(255,255,255,0.05)',color:'var(--text-primary)',outline:'none'}

  if(stage==='review'){
    return(
      <div className="modal-overlay open" onClick={e=>e.target===e.currentTarget&&onClose()}>
        <div className="modal-box" style={{maxWidth:600,maxHeight:'80vh',overflowY:'auto'}}>
          <button onClick={onClose} style={{position:'absolute',top:14,right:16,fontSize:16,background:'none',border:'none',color:'var(--text-muted)',cursor:'pointer'}}>✕</button>
          <h2 className="modal-title text-primary">Review Parsed Bets</h2>

          {(parsedData?.fliff_balance||0)>0&&(
            <div style={{padding:'10px 14px',background:'rgba(74,222,128,0.06)',border:'1px solid rgba(74,222,128,0.2)',borderRadius:8,marginBottom:14,display:'flex',alignItems:'center',gap:10}}>
              <span style={{fontSize:12,color:'var(--green)',fontWeight:600}}>Fliff Balance detected: ${parseFloat(parsedData.fliff_balance).toFixed(2)}</span>
              <label style={{display:'flex',alignItems:'center',gap:5,marginLeft:'auto',cursor:'pointer',fontSize:11,color:'var(--text-dim)'}}>
                <input type="checkbox" checked={updateBalance} onChange={e=>setUpdateBalance(e.target.checked)} style={{cursor:'pointer'}}/>
                Update my Fliff balance
              </label>
            </div>
          )}

          {parsedData?.parse_notes&&(
            <div style={{fontSize:10,color:'var(--text-muted)',fontStyle:'italic',marginBottom:10,padding:'6px 10px',background:'rgba(255,255,255,0.02)',borderRadius:6}}>{parsedData.parse_notes}</div>
          )}

          {reviewBets.length===0
            ?<div style={{fontSize:12,color:'var(--text-muted)',textAlign:'center',padding:'20px 0'}}>No bets found in screenshot.</div>
            :reviewBets.map(b=>{
              const isWin=b.result==='win', isLoss=b.result==='loss', isPending=b.result==='pending'
              const badgeColor=isWin?'var(--green)':isLoss?'var(--red)':'var(--text-muted)'
              const badgeBg=isWin?'rgba(74,222,128,0.12)':isLoss?'rgba(248,113,113,0.12)':'rgba(255,255,255,0.06)'
              const badgeBorder=isWin?'rgba(74,222,128,0.3)':isLoss?'rgba(248,113,113,0.3)':'rgba(255,255,255,0.15)'
              const badgeLabel=isWin?'WIN':isLoss?'LOSS':'PENDING'
              return(
                <div key={b._id} style={{marginBottom:10,padding:'12px 14px',background:b.included?'rgba(255,255,255,0.03)':'rgba(255,255,255,0.01)',border:`1px solid ${b.included?'rgba(255,255,255,0.08)':'rgba(255,255,255,0.03)'}`,borderRadius:8,opacity:b.included?1:0.45}}>
                  <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:8}}>
                    <span style={{fontSize:11,fontWeight:700,padding:'2px 8px',borderRadius:4,background:badgeBg,color:badgeColor,border:`1px solid ${badgeBorder}`,letterSpacing:1}}>{badgeLabel}</span>
                    <span style={{fontSize:9,padding:'1px 6px',borderRadius:3,background:b.type==='parlay'?'rgba(167,139,250,0.12)':'rgba(201,168,76,0.08)',color:b.type==='parlay'?'var(--purple)':'var(--gold)',border:b.type==='parlay'?'1px solid rgba(167,139,250,0.25)':'1px solid rgba(201,168,76,0.2)',fontWeight:700,letterSpacing:1,textTransform:'uppercase'}}>{b.type==='parlay'?'PARLAY':'STRAIGHT'}</span>
                    {b.sport&&<span style={{fontSize:9,padding:'1px 6px',borderRadius:3,background:'rgba(255,255,255,0.05)',color:'var(--text-muted)',border:'1px solid rgba(255,255,255,0.08)',fontWeight:600}}>{b.sport}</span>}
                    <label style={{marginLeft:'auto',display:'flex',alignItems:'center',gap:5,cursor:'pointer',fontSize:11,color:'var(--text-muted)'}}>
                      <input type="checkbox" checked={b.included} onChange={()=>toggleBet(b._id)} style={{cursor:'pointer'}}/>
                      Include
                    </label>
                  </div>
                  <div style={{display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:8,marginBottom:8}}>
                    <div><div style={{fontSize:8,color:'var(--text-muted)',letterSpacing:1,marginBottom:2}}>ODDS</div><div style={{fontFamily:'"IBM Plex Mono",monospace',fontSize:11,color:'var(--gold)'}}>{b.odds||'—'}</div></div>
                    <div><div style={{fontSize:8,color:'var(--text-muted)',letterSpacing:1,marginBottom:2}}>STAKE</div><div style={{fontFamily:'"IBM Plex Mono",monospace',fontSize:11}}>${parseFloat(b.stake||0).toFixed(2)}</div></div>
                    <div><div style={{fontSize:8,color:'var(--text-muted)',letterSpacing:1,marginBottom:2}}>PAYOUT</div><div style={{fontFamily:'"IBM Plex Mono",monospace',fontSize:11}}>${parseFloat(b.payout||0).toFixed(2)}</div></div>
                    <div><div style={{fontSize:8,color:'var(--text-muted)',letterSpacing:1,marginBottom:2}}>PROFIT</div><div style={{fontFamily:'"IBM Plex Mono",monospace',fontSize:11,fontWeight:600,color:(b.profit||0)>0?'var(--green)':isLoss?'var(--red)':'var(--text-muted)'}}>{isLoss?`-$${parseFloat(b.stake||0).toFixed(2)}`:`+$${parseFloat(b.profit||0).toFixed(2)}`}</div></div>
                  </div>
                  <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:(b.legs&&b.legs.length)?8:0}}>
                    <span style={{fontSize:9,color:'var(--text-muted)',letterSpacing:1}}>DATE</span>
                    {b.date
                      ?<input type="date" value={b.date} onChange={e=>updateDate(b._id,e.target.value)} style={{...inp,fontSize:10,padding:'2px 6px'}}/>
                      :<input type="date" defaultValue={new Date().toISOString().split('T')[0]} onChange={e=>updateDate(b._id,e.target.value)} style={{...inp,fontSize:10,padding:'2px 6px'}}/>
                    }
                  </div>
                  {(b.legs&&b.legs.length>0)&&(
                    <div style={{marginTop:6,paddingTop:6,borderTop:'1px solid rgba(255,255,255,0.05)'}}>
                      {b.legs.map((leg,li)=>{
                        const legHit=leg.result==='hit', legMiss=leg.result==='miss'
                        return(
                          <div key={li} style={{display:'flex',alignItems:'center',gap:6,padding:'3px 0',fontSize:10}}>
                            <span style={{color:legHit?'var(--green)':legMiss?'var(--red)':'var(--text-muted)',fontSize:12,minWidth:14}}>{legHit?'✓':legMiss?'✗':'○'}</span>
                            <span style={{color:'var(--text-dim)',flex:1,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{leg.pick||leg.teams||'—'}</span>
                            {leg.bet_type&&<span style={{fontSize:8,color:'var(--text-muted)',background:'rgba(255,255,255,0.04)',padding:'1px 5px',borderRadius:3,border:'1px solid rgba(255,255,255,0.06)',flexShrink:0}}>{leg.bet_type}</span>}
                            <span style={{fontFamily:'"IBM Plex Mono",monospace',color:'var(--gold)',flexShrink:0}}>{leg.odds||''}</span>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              )
            })
          }

          {error&&<div style={{fontSize:11,color:'var(--red)',padding:'8px 10px',background:'rgba(248,113,113,0.06)',border:'1px solid rgba(248,113,113,0.2)',borderRadius:6,marginTop:8}}>{error}</div>}

          <div style={{display:'flex',gap:8,justifyContent:'flex-end',marginTop:16}}>
            <button className="mbtn cancel" onClick={()=>setStage('upload')}>← Back</button>
            <button className="mbtn cancel" onClick={onClose}>Cancel</button>
            <button className="mbtn save" onClick={handleConfirm} disabled={saving||reviewBets.filter(b=>b.included).length===0} style={{opacity:(saving||reviewBets.filter(b=>b.included).length===0)?0.5:1}}>
              {saving?'Saving…':`Confirm & Save (${reviewBets.filter(b=>b.included).length})`}
            </button>
          </div>
        </div>
      </div>
    )
  }

  // Stage: upload
  return(
    <div className="modal-overlay open" onClick={e=>e.target===e.currentTarget&&onClose()}>
      <div className="modal-box" style={{maxWidth:440}}>
        <button onClick={onClose} style={{position:'absolute',top:14,right:16,fontSize:16,background:'none',border:'none',color:'var(--text-muted)',cursor:'pointer'}}>✕</button>
        <h2 className="modal-title text-primary">Import Fliff Screenshot</h2>

        <div
          onDragOver={e=>{e.preventDefault();setDragOver(true)}}
          onDragLeave={()=>setDragOver(false)}
          onDrop={e=>{e.preventDefault();setDragOver(false);const f=e.dataTransfer.files[0];if(f)handleFile(f)}}
          onClick={()=>fileRef.current?.click()}
          style={{
            border:`2px dashed ${dragOver?'rgba(201,168,76,0.6)':file?'rgba(74,222,128,0.4)':'rgba(255,255,255,0.12)'}`,
            borderRadius:10,padding:'32px 24px',textAlign:'center',cursor:'pointer',
            background:dragOver?'rgba(201,168,76,0.04)':file?'rgba(74,222,128,0.04)':'rgba(255,255,255,0.01)',
            transition:'all .2s',marginBottom:14,
          }}
        >
          <input ref={fileRef} type="file" accept=".png,.jpg,.jpeg,.heic,.heif,image/*" style={{display:'none'}} onChange={e=>handleFile(e.target.files[0])}/>
          {file
            ?<><div style={{fontSize:24,marginBottom:6}}>📸</div><div style={{fontSize:12,color:'var(--green)',fontWeight:600}}>{file.name}</div><div style={{fontSize:10,color:'var(--text-muted)',marginTop:4}}>Click to change</div></>
            :<><div style={{fontSize:28,marginBottom:8}}>📷</div><div style={{fontSize:12,color:'var(--text-dim)',marginBottom:4}}>Drag & drop or click to upload</div><div style={{fontSize:10,color:'var(--text-muted)'}}>PNG, JPG, HEIC (iPhone screenshots)</div></>
          }
        </div>

        {error&&<div style={{fontSize:11,color:'var(--red)',padding:'8px 10px',background:'rgba(248,113,113,0.06)',border:'1px solid rgba(248,113,113,0.2)',borderRadius:6,marginBottom:12}}>{error}</div>}

        {loading&&(
          <div style={{textAlign:'center',padding:'10px 0 4px',fontSize:11,color:'var(--text-muted)',fontStyle:'italic'}}>
            <span style={{display:'inline-block',marginRight:6}}>⏳</span>
            Reading your screenshot… this takes about 10 seconds
          </div>
        )}

        <div style={{display:'flex',gap:8,justifyContent:'flex-end',marginTop:loading?6:0}}>
          <button className="mbtn cancel" onClick={onClose}>Cancel</button>
          <button className="mbtn save" onClick={handleParse} disabled={!file||loading} style={{opacity:(!file||loading)?0.5:1,background:loading?undefined:'rgba(201,168,76,0.15)',borderColor:'rgba(201,168,76,0.4)',color:'var(--gold)'}}>
            {loading?'Parsing…':'Parse Bets'}
          </button>
        </div>
      </div>
    </div>
  )
}

function SkeletonTable(){return<div className="glass" style={{padding:16}}>{[1,2,3].map(i=><div key={i} className="animate-pulse-slow" style={{height:32,background:'rgba(255,255,255,0.03)',borderRadius:4,marginBottom:4}}/>)}</div>}
