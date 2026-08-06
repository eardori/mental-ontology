#!/usr/bin/env python3
"""Compute cross-cutting META-PATTERNS over the ontology and write them into objects.json.

Individual models are granular; meta-patterns are the recurring THEMES that many models
share (e.g. "structural lock-in & moat", "AI-native transformation"). They give the viewer
a top-down layer so the shape of someone's thinking is visible at a glance, and they update
automatically as models are added.

Themes are defined transparently below (title, desc, id/keyword matchers). A model can belong
to several. Edit THEMES to refine. Output: objects.json top-level `meta_patterns`:
  [{id, title, desc, model_ids:[...], count, people:[...], top_evidence:"high|mid"}]

Usage: python3 build_meta.py <corpus_path>
"""
import json, os, re, sys

# (id, 제목, 설명, [매칭 토큰])  — 토큰은 주로 model-id 조각(정밀). 너무 흔한 한글어(관계·신뢰·데이터)는
# 광범위 매칭을 유발하므로 피하고, 변별력 있는 id 조각을 우선한다. 한 모델이 여러 테마에 속할 수 있다.
THEMES = [
 ("moat-lockin", "구조적 락인 · 해자",
  "가치를 지키는 방식은 기능이 아니라 전환비용·연결 개수·번들이라는 구조로 만든다.",
  ["lockin","-moat","connectivity","not-features","bundle","volume-as-leverage","mcp-layer","incumbent","promo-program","supply-first","platform-api","api-first-ecosystem","커넥티비티","해자"]),
 ("ai-native", "AI 네이티브 전환",
  "AI로 개발·운영의 비용 장벽이 무너지는 전제 위에서 조직·제품·전략을 다시 짠다.",
  ["ai-agents","ai-10x","ai-early","ai-transformation","triple-cloning","dev-barrier","dev-productivity","self-discovery","comprehension-resistance","documentation-ai-memory","llm-capability","llm-as-simulation","llm-era","mcp-layer","api-first-ecosystem"]),
 ("relations-luck-trust", "관계 · 운 · 신뢰 자본",
  "사람을 끊지 않고 신뢰·무해함으로 쌓는 것이 통제 가능한 운이자 장기 자본이라 본다.",
  ["relations-never-cut","luck-controllable","trust-integrity-over-money","trust-over-hype","business-friendship","harmlessness","founder-responsibility","block-as-signal","standard-based-giver","ender-relationship","negotiation-leverage","mutual-upside","partnership-longgame"]),
 ("financial-discipline", "재무 규율",
  "성장은 현금 건전성·테이크레이트·반복매출·지출 ROI라는 규율 안에서만 유효하다.",
  ["finance-","take-rate","recurring-revenue","spend-roi","price-discipline","runway","protect-existing","conservative-buffer","usage-based-revenue","data-driven-decision","profit-over-gmv"]),
 ("direction-essence", "방향 · 본질 우선",
  "목표보다 방향, 기술보다 고객 문제 — 본질을 좁게 잡고 나머지는 흘려보낸다.",
  ["direction-driven","means-not-end","simplicity-over-complexity","feed-the-imagination","segment-clarity","segment-specific","strengths-focus","physical-work","big-dreams-modest","tech-means"]),
 ("risk-survival", "리스크 격리 · 생존",
  "법적·재무·규제 리스크는 계약 구조로 격리하고, 위기에는 생존을 모든 것에 우선한다.",
  ["risk-","legal-structural-separation","crisis-survival","crisis-conviction","survival-first","regulatory-redlines","channel-dependency","no-future-guarantee"]),
 ("honesty-transparency", "정직 · 투명 커뮤니케이션",
  "과장 대신 정보·신뢰, 외부보다 내부 먼저, 말보다 동작하는 증거로 소통한다.",
  ["honest-strategic","trust-over-hype","integrity-no-shortcut","internal-first","written-commitments","show-dont-tell","integrity-over-money"]),
 ("energy-sustainability", "에너지 · 지속가능성",
  "에너지 총량을 상류 변수로 관리하고, 몸집을 줄여 오래 탈 수 있는 파도를 고른다.",
  ["energy-first","evening-cap","personal-meaning","big-dreams-modest","wave-riding","minus-approach","standard-based-giver"]),
 ("experiment-measure", "실험 · 측정 기반 의사결정",
  "확신보다 실험, 감보다 숫자 — 데이터를 쌓아 결정을 시뮬레이션하고 편향마저 도구로 쓴다.",
  ["measure-causal-loop","llm-as-simulation","data-driven-decision","data-freshness","confirmation-bias-as-power","data-supply-dynamics","expert-crosscheck"]),
 ("hiring-org-adoption", "채용 · 조직 변화 설계",
  "끈기형 인재를 압박으로 가려내고, 변화는 강요가 아니라 본인이 발견하게 설계한다.",
  ["hire-grit","adoption-self-discovery","key-talent-variable","resource-ambition","delegation-codecision","respect-team-diversity","triple-cloning","no-dragging-unwilling"]),
]

def matches(model, kws):
    mid = model["id"].lower()
    # id 조각은 정밀 매칭 우선; 한글 토큰(2자+ 한글)만 title/desc까지 확장
    for k in kws:
        kl = k.lower()
        if kl in mid:
            return True
        if re.search(r"[가-힣]", k) and k in (model.get("title","") + " " + model.get("desc","")):
            return True
    return False

def main():
    corpus = sys.argv[1]
    p = os.path.join(corpus, "_ontology", "objects.json")
    d = json.load(open(p, encoding="utf-8"))
    models = d["models"]
    mp = []
    for tid, title, desc, kws in THEMES:
        mids = [m["id"] for m in models if matches(m, kws)]
        if not mids:
            continue
        ms = [m for m in models if m["id"] in mids]
        ppl = sorted({h for m in ms for h in m.get("holders", [])})
        mp.append({
            "id": tid, "title": title, "desc": desc,
            "model_ids": mids, "count": len(mids),
            "people": ppl,
            "top_evidence": "high" if any(m.get("evidence") == "high" for m in ms) else "mid",
        })
    mp.sort(key=lambda x: -x["count"])
    d["meta_patterns"] = mp
    json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    covered = len({mid for t in mp for mid in t["model_ids"]})
    print(f"meta_patterns: {len(mp)} themes | {covered}/{len(models)} models covered")
    for t in mp:
        print(f"  {t['count']:3d}  {t['id']:22s} {t['title']}")

if __name__ == "__main__":
    main()
