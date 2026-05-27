/**
 * DemoContext — provides demo mode flag + helpers for fake realistic values
 *
 * Usage:
 *   import { useDemo, fakeAmt, demoAcctName, demoSrc } from '../context/DemoContext.jsx'
 *   const demo = useDemo()  // boolean
 *   if (demo) fmtDol(fakeAmt('nw', 45000, 85000))
 */
import { createContext, useContext } from 'react'

// ── Deterministic seeded random [0,1) ─────────────────────────────────────
function seeded(key) {
  let h = 5381
  for (let i = 0; i < key.length; i++) {
    h = (((h << 5) + h) ^ key.charCodeAt(i)) >>> 0
  }
  return h / 0xFFFFFFFF
}

/** Returns a stable fake dollar amount in [min, max] for the given key. */
export function fakeAmt(key, min, max) {
  return +(min + seeded(key) * (max - min)).toFixed(2)
}

// ── Account name substitutions ────────────────────────────────────────────
const ACCT_MAP = {
  'robinhood':      'Brokerage Account',
  'tradelocker':    'Trading Account',
  'trust wallet':   'Crypto Wallet',
  'checking':       'Bank Account — Checking',
  'truist one mma': 'Bank Account — Savings',
  'truist mma':     'Bank Account — Savings',
  'mma':            'Bank Account — Savings',
  'life insurance': 'Insurance Account',
  'ins':            'Insurance Account',
}

/** Return a generic account label when in demo mode. */
export function demoAcctName(name) {
  const k = (name || '').toLowerCase()
  for (const [pat, rep] of Object.entries(ACCT_MAP)) {
    if (k.includes(pat)) return rep
  }
  return name
}

/** Anonymize a transaction source string. */
export function demoSrc(source) {
  const s = (source || '').toUpperCase()
  if (/JASE|CASH.?APP|CASHAPP/.test(s))   return 'Transfer - Deposit'
  if (s.includes('VENMO'))                 return 'Digital Payment'
  if (s.includes('ZELLE'))                 return 'Bank Transfer'
  if (s.includes('PAYPAL'))                return 'Digital Payment'
  if (s.includes('TELEGRAM'))              return 'Digital Payment'
  if (s.includes('DIRECT DEP'))            return 'Direct Deposit'
  if (s.includes('WIRE'))                  return 'Wire Transfer'
  return 'Income - Deposit'
}

// ── Context ───────────────────────────────────────────────────────────────
const DemoContext = createContext(false)

/** Wrap the app to propagate demo mode. */
export function DemoProvider({ demo, children }) {
  return <DemoContext.Provider value={!!demo}>{children}</DemoContext.Provider>
}

/** Returns true when ?demo=true is in the URL. */
export function useDemo() {
  return useContext(DemoContext)
}
