# backend/services/diet_service.py
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections import defaultdict
import pandas as pd

# ---- CSV locations (project root) ----
ROOT = Path(__file__).resolve().parents[2]  # services -> backend -> project root
FIXED_CSV = ROOT / "fixed_ingredients.csv"
USER_CSV  = ROOT / "user_ingredients.csv"

# in-memory dataframes
_fixed_df: Optional[pd.DataFrame] = None
_user_df: Optional[pd.DataFrame] = None

REQUIRED_FIXED = {
    "ingredient_name","dm_g","protein_g","fat_g","cho_g","fiber_g","ash_g",
    "calcium_mg","phosphorus_mg","iron_mg","energy_kcal"
}
REQUIRED_USER = {
    "ingredient_name","group_name","protein_g","fat_g","cho_g","fiber_g","ash_g",
    "calcium_mg","phosphorus_mg","iron_mg","energy_kcal"
}

# ---------- tiny utils ----------
def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    return df

def _normkey(s: str) -> str:
    return " ".join(
        str(s).lower()
        .replace(",", " ").replace("–", "-").replace("—", "-")
        .replace("’", "'").replace("`", "'")
        .split()
    )

def _is_like(name: str, needle: str) -> bool:
    return needle in _normkey(name)

# “special” Meat-A items that can be capped at 75 g when 2+ Meat-A items are selected
def _is_capped_meat_a(name: str) -> bool:
    nk = _normkey(name)
    return ("egg white" in nk) or ("shrimp" in nk) or ("oyster" in nk)

# ---------- IO ----------
def load_csvs() -> dict:
    global _fixed_df, _user_df
    f = _norm_cols(pd.read_csv(FIXED_CSV))
    u = _norm_cols(pd.read_csv(USER_CSV))

    if not REQUIRED_FIXED.issubset(f.columns):
        missing = list(REQUIRED_FIXED - set(f.columns))
        raise RuntimeError(f"{FIXED_CSV.name} missing columns: {missing}")
    if not REQUIRED_USER.issubset(u.columns):
        missing = list(REQUIRED_USER - set(u.columns))
        raise RuntimeError(f"{USER_CSV.name} missing columns: {missing}")

    _fixed_df, _user_df = f, u
    return {"ok": True, "fixed_rows": len(_fixed_df), "user_rows": len(_user_df)}

# load once on import
load_csvs()

def fixed_df() -> pd.DataFrame:
    return _fixed_df

def user_df() -> pd.DataFrame:
    return _user_df

# ---------- accumulation helpers ----------
FIXED_TOTAL_DM = 1000.0

def _add_to_totals(totals: Dict[str, float], dm: float, row: pd.Series):
    """Add nutrient contribution of 'dm' grams from per-100g row."""
    totals["Protein"] += float(row["protein_g"]) * dm / 100.0
    totals["Fat"]     += float(row["fat_g"])     * dm / 100.0
    totals["CHO"]     += float(row["cho_g"])     * dm / 100.0
    totals["Fiber"]   += float(row["fiber_g"])   * dm / 100.0
    totals["Ash"]     += float(row["ash_g"])     * dm / 100.0
    totals["Ca"]      += float(row["calcium_mg"])    * dm / 100.0 / 1000.0
    totals["P"]       += float(row["phosphorus_mg"]) * dm / 100.0 / 1000.0
    totals["Iron"]    += float(row["iron_mg"])       * dm / 100.0
    totals["Energy"]  += float(row["energy_kcal"])   * dm / 100.0

def _compress_breakdown(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Combine multiple entries for same ingredient for dm_breakdown."""
    agg = defaultdict(lambda: {"ingredient": "", "dm_g": 0.0, "fixed": False})
    for row in raw:
        name = row["ingredient"]
        agg[name]["ingredient"] = name
        agg[name]["dm_g"] = round(agg[name]["dm_g"] + float(row["dm_g"]), 2)
        agg[name]["fixed"] = agg[name]["fixed"] or bool(row.get("fixed", False))
    merged = list(agg.values())
    merged.sort(key=lambda r: (not r["fixed"], r["ingredient"].lower()))
    return merged

# ---------- main ----------
def calculate_diet(selected_names: List[str]) -> Dict[str, Any]:
    """
    Implements:
      * Organs:
          - liver only → 120 g
          - liver + other organ(s) → liver 100 g, other organ(s) 50 g total
      * Oils: 10 g total (with special 3 g salmon oil if chosen)
      * Vegetables:
          - A only 80 g; B only 70 g; both: A 70 g + B 30 g
          - Veg C (potato) ≤ 100 g
      * Grains:
          - if potato selected → total grains (A+B) in [200, 300]
          - else → total grains (A+B) in [300, 400]
          - Grain B in [140, 200] (midpoint ~170); Grain A fills the window (per-item cap 150 g)
      * Meat:
          - default meat target 280 g (clamped to 200–350 and remaining)
          - If ONLY Meat-C chosen → meat total forced to 25–35 g
          - If ONLY Meat-B chosen → auto-add lean Meat-A and aim for ~150 g Meat-A
          - Meat-B total is capped at 50 g
          - Meat-A special items (egg white / shrimp / oyster) are capped at 75 g
            only when 2+ Meat-A items exist; otherwise no cap.

      Post rules:
        - If Protein% > 40: move 25 g from Meat-A to Grains (prefer A, else B) within windows.
        - If Protein% < 32: add 5 g from Meat-B (respect Meat-B cap and meat max).
        - If Fat% < 12: add up to 50 g Meat-B (respect Meat-B cap and meat max).

      Always normalize back to exactly 1000 g DM after post-rules.
    """
    fdf = fixed_df()
    udf = user_df()

    # --- running state ---
    totals = {k: 0.0 for k in ["Protein", "Fat", "CHO", "Fiber", "Ash", "Ca", "P", "Iron", "Energy"]}
    issues: List[str] = []
    dm_breakdown_raw: List[Dict[str, Any]] = []
    ingredient_totals: List[Dict[str, Any]] = []
    auto_added: Dict[str, Any] = {}

    remaining = FIXED_TOTAL_DM  # remaining DM to allocate

    # --------- helpers bound to this run ----------
    def _find_row(name: str) -> Optional[pd.Series]:
        sr = udf[udf["ingredient_name"].str.lower() == name.lower()]
        if not sr.empty:
            return sr.iloc[0]
        sr = fdf[fdf["ingredient_name"].str.lower() == name.lower()]
        return sr.iloc[0] if not sr.empty else None

    def _add_item(row: pd.Series, dm: float, fixed: bool = False) -> float:
        nonlocal remaining
        if dm <= 0 or remaining <= 0:
            return 0.0
        dm = round(min(dm, remaining), 2)
        name = str(row["ingredient_name"])

        _add_to_totals(totals, dm, row)
        dm_breakdown_raw.append({"ingredient": name, "dm_g": dm, "fixed": fixed})

        # merge with existing ingredient_totals if present
        for it in ingredient_totals:
            if it["ingredient"] == name and bool(it.get("fixed", False)) == fixed:
                base = it["dm_g"]
                for k, col in [
                    ("protein_g", "protein_g"),
                    ("fat_g", "fat_g"),
                    ("cho_g", "cho_g"),
                    ("fiber_g", "fiber_g"),
                    ("ash_g", "ash_g"),
                    ("ca_mg", "calcium_mg"),
                    ("p_mg", "phosphorus_mg"),
                    ("iron_mg", "iron_mg"),
                    ("energy_kcal", "energy_kcal"),
                ]:
                    it[k] = round(it[k] + float(row[col]) * dm / 100.0, 2)
                it["dm_g"] = round(base + dm, 2)
                remaining = round(remaining - dm, 2)
                return dm

        ingredient_totals.append({
            "ingredient": name,
            "dm_g": dm,
            "protein_g":   round(float(row["protein_g"])   * dm / 100.0, 2),
            "fat_g":       round(float(row["fat_g"])       * dm / 100.0, 2),
            "cho_g":       round(float(row["cho_g"])       * dm / 100.0, 2),
            "fiber_g":     round(float(row["fiber_g"])     * dm / 100.0, 2),
            "ash_g":       round(float(row["ash_g"])       * dm / 100.0, 2),
            "ca_mg":       round(float(row["calcium_mg"])  * dm / 100.0, 2),
            "p_mg":        round(float(row["phosphorus_mg"]) * dm / 100.0, 2),
            "iron_mg":     round(float(row["iron_mg"])       * dm / 100.0, 2),
            "energy_kcal": round(float(row["energy_kcal"])   * dm / 100.0, 2),
            "fixed": fixed,
        })
        remaining = round(remaining - dm, 2)
        return dm

    def _sum_dm(items: List[Dict[str, Any]]) -> float:
        return round(sum(x["dm_g"] for x in items), 2)

    def _recompute_totals() -> Dict[str, float]:
        new = {k: 0.0 for k in totals}
        for it in ingredient_totals:
            src = _find_row(it["ingredient"])
            if src is not None:
                _add_to_totals(new, it["dm_g"], src)
        return new

    def _group_rows(names: set) -> List[Dict[str, Any]]:
        return [it for it in ingredient_totals if it["ingredient"] in names]

    def _current_dm(names: set) -> float:
        return round(sum(it["dm_g"] for it in ingredient_totals if it["ingredient"] in names), 2)

    def _shrink(it: Dict[str, Any], delta: float) -> float:
        if delta <= 0 or it["dm_g"] <= 0:
            return 0.0
        cut = min(delta, it["dm_g"])
        base = it["dm_g"]
        scale = (base - cut) / max(base, 1e-9)
        for k in ["protein_g","fat_g","cho_g","fiber_g","ash_g","ca_mg","p_mg","iron_mg","energy_kcal"]:
            it[k] = round(it[k] * scale, 2)
        it["dm_g"] = round(base - cut, 2)
        return cut

    def _grow(it: Dict[str, Any], delta: float, src_row: Optional[pd.Series] = None) -> float:
        if delta <= 0:
            return 0.0
        base = it["dm_g"]
        inc = delta
        if src_row is None:
            src_row = _find_row(it["ingredient"])
        if src_row is not None:
            it["protein_g"]   = round(it["protein_g"]   + float(src_row["protein_g"])   * inc / 100.0, 2)
            it["fat_g"]       = round(it["fat_g"]       + float(src_row["fat_g"])       * inc / 100.0, 2)
            it["cho_g"]       = round(it["cho_g"]       + float(src_row["cho_g"])       * inc / 100.0, 2)
            it["fiber_g"]     = round(it["fiber_g"]     + float(src_row["fiber_g"])     * inc / 100.0, 2)
            it["ash_g"]       = round(it["ash_g"]       + float(src_row["ash_g"])       * inc / 100.0, 2)
            it["ca_mg"]       = round(it["ca_mg"]       + float(src_row["calcium_mg"])  * inc / 100.0, 2)
            it["p_mg"]        = round(it["p_mg"]        + float(src_row["phosphorus_mg"]) * inc / 100.0, 2)
            it["iron_mg"]     = round(it["iron_mg"]     + float(src_row["iron_mg"])     * inc / 100.0, 2)
            it["energy_kcal"] = round(it["energy_kcal"] + float(src_row["energy_kcal"]) * inc / 100.0, 2)
        it["dm_g"] = round(base + inc, 2)
        return inc

    # ---------- collect picks (unique, robust match) ----------
    seen_keys: set = set()
    picks: List[pd.Series] = []
    for name in selected_names:
        key = _normkey(name)
        if key in seen_keys:
            continue
        rows = udf[udf["ingredient_name"].apply(_normkey) == key]
        if not rows.empty:
            picks.append(rows.iloc[0])
            seen_keys.add(key)

    def G(s: pd.Series) -> str:
        return str(s.get("group_name", "")).strip().lower()

    meats_a = [r for r in picks if "meat group a" in G(r)]
    meats_b = [r for r in picks if "meat group b" in G(r)]
    meats_c = [r for r in picks if "meat group c" in G(r)]
    grains_a = [r for r in picks if "grain a" in G(r)]
    grains_b = [r for r in picks if "grain b" in G(r)]
    veg_a    = [r for r in picks if "vegetable a" in G(r)]
    veg_b    = [r for r in picks if "vegetable b" in G(r)]
    veg_c    = [r for r in picks if "vegetable c" in G(r)]
    oils     = [r for r in picks if "oil" in G(r)]
    fruits   = [r for r in picks if "fruit" in G(r)]
    organs   = [r for r in picks if "organ" in G(r) and not _is_like(r["ingredient_name"], "liver")]
    livers   = [r for r in picks if _is_like(r["ingredient_name"], "liver")]

    # ---------- 0) Fixed items ----------
    for _, r in fdf.iterrows():
        dm = float(r["dm_g"])
        if dm > 0:
            _add_item(r, dm, fixed=True)

    # ---------- 1) Organs ----------
    LIVER_SOLO_DM = 120.0   # only liver selected
    LIVER_DM      = 100.0   # when other organs also chosen
    OTHER_ORG_DM  = 50.0    # total for other organs when present

    if livers and not organs:
        _add_item(livers[0], LIVER_SOLO_DM)
    elif livers and organs:
        _add_item(livers[0], LIVER_DM)
        per = OTHER_ORG_DM / len(organs)
        acc = 0.0
        for i, r in enumerate(organs):
            dm = per if i < len(organs) - 1 else round(OTHER_ORG_DM - acc, 2)
            acc += dm
            _add_item(r, dm)
    else:
        issues.append("Liver is mandatory but not selected.")

    # ---------- 2) Oils ----------
    OILS_DM = 10.0
    SALMON_OIL_DM = 3.0
    if oils:
        salmon_oil = [r for r in oils if _is_like(r["ingredient_name"], "salmon oil")]
        other_oils = [r for r in oils if r not in salmon_oil]
        if salmon_oil:
            _add_item(salmon_oil[0], SALMON_OIL_DM)
            if other_oils:
                per = OILS_DM / len(other_oils)
                acc = 0.0
                for i, r in enumerate(other_oils):
                    dm = per if i < len(other_oils) - 1 else round(OILS_DM - acc, 2)
                    acc += dm
                    _add_item(r, dm)
        else:
            per = OILS_DM / len(oils)
            acc = 0.0
            for i, r in enumerate(oils):
                dm = per if i < len(oils) - 1 else round(OILS_DM - acc, 2)
                acc += dm
                _add_item(r, dm)
    else:
        issues.append("No oil selected; cannot allocate 10 g total oils.")

    # ---------- 3) Vegetables ----------
    VEG_A_ONLY_DM = 80.0
    VEG_B_ONLY_DM = 70.0
    VEG_AB_A_DM   = 70.0
    VEG_AB_B_DM   = 30.0
    POTATO_MAX_DM = 100.0

    vegA_selected = bool(veg_a)
    vegB_selected = bool(veg_b)
    potato_selected = bool(veg_c)

    if vegA_selected and vegB_selected:
        per_a = VEG_AB_A_DM / len(veg_a)
        acc = 0.0
        for i, r in enumerate(veg_a):
            dm = per_a if i < len(veg_a) - 1 else round(VEG_AB_A_DM - acc, 2)
            acc += dm
            _add_item(r, dm)
        per_b = VEG_AB_B_DM / len(veg_b)
        acc = 0.0
        for i, r in enumerate(veg_b):
            dm = per_b if i < len(veg_b) - 1 else round(VEG_AB_B_DM - acc, 2)
            acc += dm
            _add_item(r, dm)
    elif vegA_selected:
        per = VEG_A_ONLY_DM / len(veg_a)
        acc = 0.0
        for i, r in enumerate(veg_a):
            dm = per if i < len(veg_a) - 1 else round(VEG_A_ONLY_DM - acc, 2)
            acc += dm
            _add_item(r, dm)
    elif vegB_selected:
        per = VEG_B_ONLY_DM / len(veg_b)
        acc = 0.0
        for i, r in enumerate(veg_b):
            dm = per if i < len(veg_b) - 1 else round(VEG_B_ONLY_DM - acc, 2)
            acc += dm
            _add_item(r, dm)

    if potato_selected and remaining > 0:
        alloc = min(POTATO_MAX_DM, remaining)
        per = alloc / len(veg_c)
        acc = 0.0
        for i, r in enumerate(veg_c):
            dm = per if i < len(veg_c) - 1 else round(alloc - acc, 2)
            acc += dm
            _add_item(r, dm)

    # ---------- 4) Grains ----------
    if potato_selected:
        GRAIN_MIN, GRAIN_MAX = 200.0, 300.0
    else:
        GRAIN_MIN, GRAIN_MAX = 300.0, 400.0

    GRAIN_A_ITEM_CAP = 150.0
    GRAIN_B_MIN, GRAIN_B_MAX = 140.0, 200.0

    grain_a_names = {r["ingredient_name"] for r in grains_a}
    grain_b_names = {r["ingredient_name"] for r in grains_b}

    def _grain_totals() -> float:
        return round(sum(
            it["dm_g"] for it in ingredient_totals
            if it["ingredient"] in (grain_a_names | grain_b_names)
        ), 2)

    # Allocate Grain B (≈170 within [140, 200])
    if grains_b:
        gb_alloc = min(max(GRAIN_B_MIN, 170.0), GRAIN_B_MAX, remaining)
        per = gb_alloc / len(grains_b)
        acc = 0.0
        for i, r in enumerate(grains_b):
            dm = per if i < len(grains_b) - 1 else round(gb_alloc - acc, 2)
            acc += dm
            _add_item(r, dm)
    else:
        issues.append(f"No Grain B selected; cannot allocate {GRAIN_B_MIN:g}–{GRAIN_B_MAX:g} g of Grain B.")

    # Grain A fills window
    gb_used = _current_dm(grain_b_names)
    ga_target_min = max(0.0, GRAIN_MIN - gb_used)
    ga_target_max = max(0.0, GRAIN_MAX - gb_used)
    if grains_a:
        ga_dm = min(ga_target_max, remaining)
        if ga_dm < ga_target_min and remaining >= ga_target_min:
            ga_dm = ga_target_min
        per = ga_dm / len(grains_a) if grains_a else 0.0
        acc = 0.0
        for i, r in enumerate(grains_a):
            ideal = per if i < len(grains_a) - 1 else round(ga_dm - acc, 2)
            already = _current_dm({r["ingredient_name"]})
            room = max(0.0, GRAIN_A_ITEM_CAP - already)
            dm = min(ideal, room)
            acc += dm
            if dm > 0:
                _add_item(r, dm)
        # second pass honor window hard max
        need = round(ga_dm - sum(_current_dm({x["ingredient_name"]}) for x in grains_a), 2)
        if need > 0:
            for r in grains_a:
                if need <= 0:
                    break
                if _grain_totals() >= GRAIN_MAX:
                    break
                already = _current_dm({r["ingredient_name"]})
                room = max(0.0, GRAIN_A_ITEM_CAP - already)
                extra_window = max(0.0, GRAIN_MAX - _grain_totals())
                dm = min(room, need, remaining, extra_window)
                if dm > 0:
                    _add_item(r, dm)
                    need = round(need - dm, 2)
    elif ga_target_min > 0:
        issues.append(f"No Grain A selected; cannot meet grain minimum {GRAIN_MIN:g} g.")

    # ---------- 5) Meat ----------
    DEFAULT_MEAT_TARGET = 280.0
    MEAT_MIN    = 200.0
    MEAT_MAX    = 350.0
    MEAT_B_TOTAL_MAX = 50.0  # global cap for Meat-B grams

    def _pick_lean_meat_a() -> Optional[pd.Series]:
        all_a = udf[udf["group_name"].str.lower().str.contains("meat group a", na=False)]
        if all_a.empty:
            return None
        return all_a.sort_values(by="fat_g", ascending=True).iloc[0]

    meats_selected: List[pd.Series] = []
    if meats_a:
        meats_selected.extend(meats_a)
    if meats_b:
        meats_selected.extend(meats_b)
    if not meats_selected and meats_c:
        meats_selected.extend(meats_c)

    only_meat_b = bool(meats_b) and not meats_a and not meats_c
    only_meat_c = bool(meats_c) and not meats_a and not meats_b

    if only_meat_c:
        MEAT_TARGET = 30.0
        MEAT_MIN_THIS = 25.0
        MEAT_MAX_THIS = 35.0
    else:
        MEAT_TARGET = DEFAULT_MEAT_TARGET
        MEAT_MIN_THIS = MEAT_MIN
        MEAT_MAX_THIS = MEAT_MAX

    meat_target_dm = min(max(MEAT_MIN_THIS, min(MEAT_TARGET, MEAT_MAX_THIS)), max(0.0, remaining))

    if only_meat_b:
        lean_a = _pick_lean_meat_a()
        if lean_a is not None:
            meats_a.append(lean_a)
            meats_selected.insert(0, lean_a)
            auto_added["meat_a"] = str(lean_a["ingredient_name"])
        else:
            issues.append("Only Meat-B selected and no Meat-A available to auto-add; diet may be fatty.")

    if not meats_selected and meat_target_dm > 0:
        issues.append("No meat selected; cannot allocate meat DM.")
    elif meats_selected and meat_target_dm > 0:
        plan: Dict[str, float] = {r["ingredient_name"]: 0.0 for r in meats_selected}

        per = meat_target_dm / len(meats_selected)
        acc = 0.0
        for i, r in enumerate(meats_selected):
            dm = per if i < len(meats_selected) - 1 else round(meat_target_dm - acc, 2)
            acc += dm
            plan[r["ingredient_name"]] = round(dm, 2)

        meatA_names = [r["ingredient_name"] for r in meats_a]
        meatB_names = [r["ingredient_name"] for r in meats_b]

        apply_cap_A75 = len(meatA_names) >= 2
        if apply_cap_A75:
            overflow = 0.0
            for nm in meatA_names:
                if _is_capped_meat_a(nm) and plan.get(nm, 0.0) > 75.0:
                    overflow += plan[nm] - 75.0
                    plan[nm] = 75.0
            non_capped_A = [nm for nm in meatA_names if not _is_capped_meat_a(nm)]
            if overflow > 0 and non_capped_A:
                per_add = round(overflow / len(non_capped_A), 2)
                added = 0.0
                for i, nm in enumerate(non_capped_A):
                    inc = per_add if i < len(non_capped_A) - 1 else round(overflow - added, 2)
                    plan[nm] = round(plan.get(nm, 0.0) + inc, 2)
                    added += inc

        # enforce Meat-B ≤ 50 g
        if meatB_names:
            current_B = round(sum(plan.get(nm, 0.0) for nm in meatB_names), 2)
            if current_B > MEAT_B_TOTAL_MAX:
                remove = round(current_B - MEAT_B_TOTAL_MAX, 2)
                total_B = current_B or 1.0
                for nm in meatB_names:
                    share = plan.get(nm, 0.0) / total_B
                    cut = round(remove * share, 2)
                    plan[nm] = max(0.0, round(plan.get(nm, 0.0) - cut, 2))
                # rounding fix
                while round(sum(plan.get(nm, 0.0) for nm in meatB_names), 2) > MEAT_B_TOTAL_MAX:
                    biggest = max(meatB_names, key=lambda x: plan.get(x, 0.0))
                    plan[biggest] = round(max(0.0, plan[biggest] - 0.01), 2)

        # only-meat-B: prefer ≈150 g in Meat-A
        if only_meat_b and meatA_names:
            total_A = sum(plan.get(nm, 0.0) for nm in meatA_names)
            want_A = 150.0
            if total_A < want_A:
                delta = min(want_A - total_A, max(0.0, MEAT_MAX - sum(plan.values())))
                if delta > 0:
                    firstA = meatA_names[0]
                    plan[firstA] = round(plan.get(firstA, 0.0) + delta, 2)

        for r in meats_selected:
            dm = round(plan.get(r["ingredient_name"], 0.0), 2)
            if dm > 0:
                _add_item(r, dm)

    # ---------- 6) Fruits (simple) ----------
    FRUIT_MAX_DM = 25.0
    if fruits and remaining > 0:
        alloc = min(FRUIT_MAX_DM, remaining)
        per = alloc / len(fruits)
        acc = 0.0
        for i, r in enumerate(fruits):
            dm = per if i < len(fruits) - 1 else round(alloc - acc, 2)
            acc += dm
            _add_item(r, dm)

    # ---------- 7) Normalize to 1000 BEFORE post-rules ----------
    def _normalize_to_1000():
        nonlocal totals
        total_dm = _sum_dm(ingredient_totals)
        if abs(total_dm - FIXED_TOTAL_DM) < 0.5:
            return

        # names for groups we might grow/shrink
        ga_names = grain_a_names
        meat_names = {r["ingredient_name"] for r in meats_a + meats_b + meats_c}

        def grain_totals() -> float:
            return round(sum(it["dm_g"] for it in ingredient_totals if it["ingredient"] in (ga_names | grain_b_names)), 2)

        if total_dm < FIXED_TOTAL_DM:
            need = round(FIXED_TOTAL_DM - total_dm, 2)
            # try Grain A first, staying within window & 150/item
            if ga_names:
                for it in _group_rows(ga_names):
                    if need <= 0:
                        break
                    extra_window = max(0.0, GRAIN_MAX - grain_totals())
                    if extra_window <= 0:
                        break
                    room_item = max(0.0, GRAIN_A_ITEM_CAP - it["dm_g"])
                    add = min(need, room_item, extra_window)
                    if add > 0:
                        _grow(it, add)
                        need = round(need - add, 2)
            # then meat within MEAT_MAX; respect A-75 cap only if 2+ A
            if need > 0 and meat_names:
                meat_rows = _group_rows(meat_names)
                apply_cap_norm = len(meats_a) >= 2
                for it in meat_rows:
                    if need <= 0:
                        break
                    meat_now = sum(x["dm_g"] for x in meat_rows)
                    room = max(0.0, MEAT_MAX - meat_now)
                    if apply_cap_norm and _is_capped_meat_a(it["ingredient"]):
                        room = min(room, max(0.0, 75.0 - it["dm_g"]))
                    add = min(need, room)
                    if add > 0:
                        _grow(it, add)
                        need = round(need - add, 2)
        else:
            cut = round(total_dm - FIXED_TOTAL_DM, 2)
            # cut Grain A first but keep ≥ window min
            if ga_names:
                ga_rows = _group_rows(ga_names)
                for it in sorted(ga_rows, key=lambda x: x["dm_g"], reverse=True):
                    if cut <= 0:
                        break
                    spare_window = max(0.0, grain_totals() - GRAIN_MIN)
                    if spare_window <= 0:
                        break
                    take = min(cut, it["dm_g"], spare_window)
                    removed = _shrink(it, take)
                    cut = round(cut - removed, 2)
            # then meats but keep ≥ meat minimum (or 25 if only Meat-C)
            if cut > 0 and meat_names:
                meat_rows = _group_rows(meat_names)
                min_now = 25.0 if only_meat_c else 200.0
                for it in sorted(meat_rows, key=lambda x: x["dm_g"], reverse=True):
                    if cut <= 0:
                        break
                    meat_now = sum(x["dm_g"] for x in meat_rows)
                    spare = max(0.0, meat_now - min_now)
                    if spare <= 0:
                        break
                    take = min(cut, it["dm_g"], spare)
                    removed = _shrink(it, take)
                    cut = round(cut - removed, 2)

        totals = _recompute_totals()

    _normalize_to_1000()

    # ---------- 8) Post-rules (protein/fat) ----------
    def pct(key: str) -> float:
        return round(totals[key] * 100.0 / FIXED_TOTAL_DM, 2)

    def _find_it(name: str) -> Optional[Dict[str, Any]]:
        for it in ingredient_totals:
            if it["ingredient"].lower() == name.lower():
                return it
        return None

    # quick group helpers
    meatA_names = {r["ingredient_name"] for r in meats_a}
    meatB_names = {r["ingredient_name"] for r in meats_b}

    # P1: Protein too high → move 25 g from Meat-A to Grains (A then B)
    if pct("Protein") > 40.0 and meatA_names:
        moved = 0.0
        # take from the largest Meat-A item first
        meatA_rows = sorted([it for it in _group_rows(meatA_names)], key=lambda x: x["dm_g"], reverse=True)
        for it in meatA_rows:
            if moved >= 25.0:
                break
            take = min(25.0 - moved, it["dm_g"])
            if take > 0:
                moved += _shrink(it, take)
        if moved > 0:
            # give to Grain A within window; spill to Grain B if A is full
            to_give = moved

            # function to compute current totals
            def grain_totals_now():
                return round(sum(it["dm_g"] for it in ingredient_totals if it["ingredient"] in (grain_a_names | grain_b_names)), 2)

            # try Grain A first
            if grains_a:
                for it in _group_rows(grain_a_names):
                    if to_give <= 0:
                        break
                    extra_window = max(0.0, GRAIN_MAX - grain_totals_now())
                    if extra_window <= 0:
                        break
                    room_item = max(0.0, GRAIN_A_ITEM_CAP - it["dm_g"])
                    add = min(to_give, room_item, extra_window)
                    if add > 0:
                        _grow(it, add)
                        to_give = round(to_give - add, 2)
            # spill into Grain B if still room and Grain B selected
            if to_give > 0 and grains_b:
                gb_now = _current_dm(grain_b_names)
                gb_room = max(0.0, GRAIN_B_MAX - gb_now)
                if gb_room > 0:
                    per = min(to_give, gb_room) / len(grains_b)
                    acc = 0.0
                    for i, r in enumerate(grains_b):
                        dm = per if i < len(grains_b) - 1 else round(min(to_give, gb_room) - acc, 2)
                        acc += dm
                        if dm > 0:
                            _add_item(r, dm)
                    to_give = round(to_give - min(to_give, gb_room), 2)

        totals = _recompute_totals()

    # P2: Protein too low → add 5 g Meat-B (respect caps)
    if pct("Protein") < 32.0 and meats_b:
        # current Meat-B used:
        meatB_used = sum(it["dm_g"] for it in _group_rows(meatB_names))
        roomB = max(0.0, MEAT_B_TOTAL_MAX - meatB_used)
        add_g = min(5.0, roomB, remaining)
        if add_g > 0:
            per = add_g / len(meats_b)
            acc = 0.0
            for i, r in enumerate(meats_b):
                dm = per if i < len(meats_b) - 1 else round(add_g - acc, 2)
                acc += dm
                if dm > 0:
                    _add_item(r, dm)
            totals = _recompute_totals()

    # F1: Fat too low → add up to 50 g Meat-B (respect caps)
    if pct("Fat") < 12.0 and meats_b:
        meatB_used = sum(it["dm_g"] for it in _group_rows(meatB_names))
        roomB = max(0.0, MEAT_B_TOTAL_MAX - meatB_used)
        add_target = min(50.0, roomB, remaining)
        if add_target > 0:
            per = add_target / len(meats_b)
            acc = 0.0
            for i, r in enumerate(meats_b):
                dm = per if i < len(meats_b) - 1 else round(add_target - acc, 2)
                acc += dm
                if dm > 0:
                    _add_item(r, dm)
            totals = _recompute_totals()

    # ---------- 9) FINAL normalize to exactly 1000 after post-rules ----------
    _normalize_to_1000()

    # ---------- finalize ----------
    ingredient_totals[:] = [it for it in ingredient_totals if round(it["dm_g"], 2) > 0]

    def pct_final(key: str) -> float:
        return round(totals[key] * 100.0 / FIXED_TOTAL_DM, 2)

    result = {
        "Protein_percent": pct_final("Protein"),
        "Fat_percent": pct_final("Fat"),
        "CHO_percent": pct_final("CHO"),
        "Fiber_percent": pct_final("Fiber"),
        "Ash_percent": pct_final("Ash"),
        "Ca_percent": round(totals["Ca"] * 100.0 / FIXED_TOTAL_DM, 2),
        "P_percent": round(totals["P"] * 100.0 / FIXED_TOTAL_DM, 2),
        "Ca_P_ratio": round(totals["Ca"] / totals["P"], 2) if totals["P"] else 0.0,
        "Energy": round(totals["Energy"], 2),
        "DM_percent": FIXED_TOTAL_DM,
    }

    # gentle warnings (non-fatal)
    if not (32.0 <= result["Protein_percent"] <= 40.0):
        issues.append(f"Protein outside desired range (32–40%): {result['Protein_percent']}%.")
    if not (12.0 <= result["Fat_percent"] <= 17.0):
        issues.append(f"Fat outside desired range (12–17%): {result['Fat_percent']}%.")
    if not (3.0 <= result["Fiber_percent"] <= 6.0):
        issues.append(f"Fiber outside desired range (3–6%): {result['Fiber_percent']}%.")
    if not (4000.0 <= result["Energy"] <= 4500.0):
        issues.append(f"Energy outside desired range (4000–4500 kcal): {result['Energy']} kcal.")

    final_breakdown = _compress_breakdown(dm_breakdown_raw)
    return {
        "nutrient_percentages": result,
        "dm_breakdown": final_breakdown,
        "ingredient_totals": ingredient_totals,
        "issues": issues,
        "auto_added": auto_added if auto_added else None,
    }
