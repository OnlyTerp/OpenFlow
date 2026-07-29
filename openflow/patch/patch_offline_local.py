#!/usr/bin/env python3
"""Offline local Grok Flow: no login wall, always signed-in for dictation.

Markers: grok-flow-offline-local | grok-flow-no-login | grok-flow-force-signed-in
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

MARKER = b"grok-flow-offline-local"
NOLOGIN = b"grok-flow-no-login"
FORCE = b"grok-flow-force-signed-in"

_PATCHES_MAIN = [
    (
        b'Ur=async()=>{const e=await Pr();return e?e.accessToken:(f.RA.authSignedIn&&i().error("No session found when getting access token, after user signed in"),null)}',
        b'Ur=async()=>{try{const e=await Pr();if(e&&e.accessToken)return e.accessToken}catch(e){}return"grok-flow-local-offline-token"/*' + MARKER + b'*/}',
        "getAccessToken local",
    ),
    (
        b'jr=async()=>{const e=await Pr();return e?e.identity:(f.RA.authSignedIn&&i().error("No session found when getting user, after user signed in"),null)}',
        b'jr=async()=>{try{const e=await Pr();if(e&&e.identity)return e.identity}catch(e){}return{id:"grok-flow-local",email:"local@openflow.local",firstName:"OpenFlow",lastName:"Local",avatarUrl:null,subscription:{status:"active",daysLeft:null,plan:"FLOW_PRO_YEARLY",credits:999999,isSubscribed:!0,renewalTimestamp:4102444800,teamDomainStatus:"forbidden",isStudent:!1,sourceOfSubscription:"local",gracePeriodEndsAt:null,cancelAt:null,cancelAtPeriodEnd:!1,priceResolved:!0}}/*' + MARKER + b'*/}',
        "getUser local",
    ),
    (
        b"B=e=>{T.authSignedIn=e,(0,M.vY)({authSignedIn:e}),(0,y.MP)(e)}",
        b"B=e=>{e=!0/*" + FORCE + b"*/;T.authSignedIn=e,(0,M.vY)({authSignedIn:e}),(0,y.MP)(e)}",
        "authSignedIn setter always true",
    ),
    (
        b'if(!Z.RA.authSignedIn)return le(O.Eg.SignedOut),void(0,g.BD)("not_signed_in");',
        b'if(false/*' + FORCE + b'*/)return le(O.Eg.SignedOut),void(0,g.BD)("not_signed_in");',
        "dictation never SignedOut",
    ),
    (
        b'else if("SIGNED_OUT"===e){i().info("SUPABASE: User signed out"),(0,f.Y4)(!1)',
        b'else if("SIGNED_OUT"===e){i().info("SUPABASE: User signed out (ignored offline)"),(0,f.Y4)(!0)/*' + FORCE + b'*/',
        "ignore SUPABASE SIGNED_OUT",
    ),
    (
        b"isRecordingKeybind:!1,authSignedIn:!1,isMediaPlaying",
        b"isRecordingKeybind:!1,authSignedIn:!0/*" + MARKER + b"*/,isMediaPlaying",
        "default authSignedIn true",
    ),
    (
        b"flowState:(0,i.Y)(),authSignedIn:!1,enterpriseIpBlocked",
        b"flowState:(0,i.Y)(),authSignedIn:!0/*" + MARKER + b"*/,enterpriseIpBlocked",
        "default authSignedIn true (2)",
    ),
    # app-1.6.288 variants
    (
        b'Qr=async()=>{const e=await Fr();return e?e.accessToken:(f.RA.authSignedIn&&i().error("No session found when getting access token, after user signed in"),null)}',
        b'Qr=async()=>{try{const e=await Fr();if(e&&e.accessToken)return e.accessToken}catch(e){}return"grok-flow-local-offline-token"/*' + MARKER + b'*/}',
        "getAccessToken local (app-1.6.288)",
    ),
    (
        b'$r=async()=>{const e=await Fr();return e?e.identity:(f.RA.authSignedIn&&i().error("No session found when getting user, after user signed in"),null)}',
        b'$r=async()=>{try{const e=await Fr();if(e&&e.identity)return e.identity}catch(e){}return{id:"grok-flow-local",email:"local@openflow.local",firstName:"OpenFlow",lastName:"Local",avatarUrl:null,subscription:{status:"active",daysLeft:null,plan:"FLOW_PRO_YEARLY",credits:999999,isSubscribed:!0,renewalTimestamp:4102444800,teamDomainStatus:"forbidden",isStudent:!1,sourceOfSubscription:"local",gracePeriodEndsAt:null,cancelAt:null,cancelAtPeriodEnd:!1,priceResolved:!0}}/*' + MARKER + b'*/}',
        "getUser local (app-1.6.288)",
    ),
    (
        b"O=e=>{v.authSignedIn=e,(0,d.vY)({authSignedIn:e}),(0,l.MP)(e)}",
        b"O=e=>{e=!0/*" + FORCE + b"*/;v.authSignedIn=e,(0,d.vY)({authSignedIn:e}),(0,l.MP)(e)}",
        "authSignedIn setter always true (app-1.6.288)",
    ),
    (
        b'if(!J.RA.authSignedIn)return pe(_.Eg.SignedOut),void(0,g.BD)("not_signed_in");',
        b'if(false/*' + FORCE + b'*/)return pe(_.Eg.SignedOut),void(0,g.BD)("not_signed_in");',
        "dictation never SignedOut (app-1.6.288)",
    ),
]

_PATCHES_HUB = [
    (
        b"if(e.user.onboardingCompleted&&!mn)return(0,Y.jsx)(tme,{initialPage:n})",
        b"if(true/*grok-flow-skip-onboarding*/)return(0,Y.jsx)(tme,{initialPage:n})",
        "skip onboarding→main",
    ),
    (
        b"if(Tn||!1===p)return(0,Y.jsx)(Hs,{})",
        b"if(false/*" + NOLOGIN + b"*/)return(0,Y.jsx)(Hs,{})",
        "never Hs login shell",
    ),
    (
        b"if(Tn)return(0,Y.jsx)(Hs,{})",
        b"if(false/*" + NOLOGIN + b"*/)return(0,Y.jsx)(Hs,{})",
        "never Hs via Tn",
    ),
    (
        b"const Tn=null!=pn||n&&null!==p&&!hn",
        b"const Tn=false/*" + NOLOGIN + b"*/",
        "Tn=false",
    ),
    (
        b'Hs=()=>{const{t:e}=(0,v.Bd)("onboarding")',
        b'Hs=()=>{return null/*' + NOLOGIN + b'*/;const{t:e}=(0,v.Bd)("onboarding")',
        "Hs→null",
    ),
    (
        b"case k.PW.WelcomeBasic:return(0,Y.jsx)(XD,{})",
        b"case k.PW.WelcomeBasic:return(0,Y.jsx)(tme,{initialPage:void 0})/*" + NOLOGIN + b"*/",
        "WelcomeBasic→main",
    ),
    (
        b'm(!1),kn.m.info("User is not signed in")',
        b'm(!0)/*' + MARKER + b'*/,kn.m.info("Grok Flow offline local auth")',
        "force supabaseSignedIn true",
    ),
    # app-1.6.288 variants
    (
        b"if(e.user.onboardingCompleted&&!kn)return(0,Y.jsx)(Rbe,{initialPage:n})",
        b"if(true/*grok-flow-skip-onboarding*/)return(0,Y.jsx)(Rbe,{initialPage:n})",
        "skip onboarding to main (app-1.6.288)",
    ),
    (
        b"if(Wn||!1===g)return(0,Y.jsx)($l,{})",
        b"if(false/*" + NOLOGIN + b"*/)return(0,Y.jsx)($l,{})",
        "never login shell (app-1.6.288)",
    ),
    (
        b"case k.PW.WelcomeBasic:return(0,Y.jsx)(XI,{})",
        b"case k.PW.WelcomeBasic:return(0,Y.jsx)(Rbe,{initialPage:void 0})/*" + NOLOGIN + b"*/",
        "WelcomeBasic to main (app-1.6.288)",
    ),
    (
        b'f(!1),Ue.m.info("User is not signed in")',
        b'f(!0)/*' + MARKER + b'*/,Ue.m.info("OpenFlow offline local auth")',
        "force supabaseSignedIn true (app-1.6.288)",
    ),
]

# Public aliases (byte patterns are load-bearing; do not edit).
PATCHES_MAIN = _PATCHES_MAIN
PATCHES_HUB = _PATCHES_HUB


COLOR_MAP = {
    b"#007a5a": b"#FF6B2C",
    b"#007A5A": b"#FF6B2C",
    b"#034f46": b"#0D0D0D",
    b"#034F46": b"#0D0D0D",
    b"#18a558": b"#FF6B2C",
    b"#18A558": b"#FF6B2C",
    b"#0b8043": b"#FF8A4C",
    b"#0B8043": b"#FF8A4C",
    b"#29504b": b"#1A1A1A",
    b"#d1f2ee": b"#1F1612",
    b"#d4f6e1": b"#1F1612",
    b"#fcfcfb": b"#121212",
    b"#FCFCFB": b"#121212",
    b"#ffffeb": b"#1A1A1A",
    b"#7232a6": b"#FF6B2C",
    b"#7232A6": b"#FF6B2C",
    b"#DBA0FF": b"#FFAB7A",
    b"#dba0ff": b"#FFAB7A",
    b"#f0d7ff": b"#2A2018",
    b"#F0D7FF": b"#2A2018",
    b"#ffbcf2": b"#FF8A4C",
    b"#FFBCF2": b"#FF8A4C",
    b"#FFC1F4": b"#FF9A5C",
    b"#ffc1f4": b"#FF9A5C",
}


# Older versions of a patch body that should be upgraded to the current `new`.
# Keyed by the patch label so apply_list can swap a stale stub for the fresh one.
PRIOR_BODIES = {
    "getUser local": [
        b'return{id:"grok-flow-local",email:"local@grok.flow",avatarUrl:null}/*' + MARKER + b'*/',
        b'return{id:"grok-flow-local",email:"local@openflow.local",avatarUrl:null}/*' + MARKER + b'*/',
    ],
}


def apply_list(data: bytes, patches: list) -> bytes:
    for old, new, label in patches:
        if new in data:
            print(f"  already/skip: {label}")
            continue
        if old in data:
            n = data.count(old)
            data = data.replace(old, new)
            print(f"  OK: {label} (x{n})")
            continue
        # Upgrade: replace a stale prior stub (same patch, older body) if present.
        for prior in PRIOR_BODIES.get(label, []):
            if prior in data:
                data = data.replace(prior, new)
                print(f"  UPGRADED: {label}")
                break
        else:
            print(f"  MISS: {label}", file=sys.stderr)
    return data


def recolor(data: bytes) -> bytes:
    n = 0
    for a, b in COLOR_MAP.items():
        c = data.count(a)
        if c:
            data = data.replace(a, b)
            n += c
    if n:
        print(f"  OK: color swaps x{n}")
    return data


def patch_extract(extract: Path) -> None:
    main = extract / ".webpack" / "main" / "index.js"
    hub = extract / ".webpack" / "renderer" / "hub" / "index.js"
    status = extract / ".webpack" / "renderer" / "status" / "index.js"
    print("offline-local patch:", extract)
    if not main.is_file():
        raise SystemExit(f"missing {main}")
    m = apply_list(main.read_bytes(), _PATCHES_MAIN)
    # NOTE: recolor() disabled — mass hex swaps caused hybrid white/dark boxes
    # and broken UI. Keep stock palette; brand via strings only.
    main.write_bytes(m)
    print("wrote", main)
    if hub.is_file():
        h = apply_list(hub.read_bytes(), _PATCHES_HUB)
        for a, b in ((b"Wispr Flow", b"OpenFlow"), (b"WisprFlow", b"OpenFlow"), (b"Grok Flow", b"OpenFlow")):
            if a in h:
                c = h.count(a)
                h = h.replace(a, b)
                print(f"  OK: hub {a.decode()}->{b.decode()} x{c}")
        hub.write_bytes(h)
        print("wrote", hub)
    if status.is_file():
        s = status.read_bytes()
        for a, b in ((b"Wispr Flow", b"OpenFlow"), (b"WisprFlow", b"OpenFlow"), (b"Grok Flow", b"OpenFlow")):
            s = s.replace(a, b)
        status.write_bytes(s)
        print("wrote", status)
    (extract / "grok-flow-offline-local.marker").write_text("offline local + no login\n")
    print("done")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("extract_dir", type=Path)
    args = ap.parse_args()
    if not args.extract_dir.is_dir():
        raise SystemExit(f"not a dir: {args.extract_dir}")
    patch_extract(args.extract_dir)


if __name__ == "__main__":
    main()
