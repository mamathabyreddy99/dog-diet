# backend/services/diet_service.py
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import pandas as pd
from collections import defaultdict

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

def _norm(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    return df

def load_csvs() -> dict:
    """(Re)load CSVs into memory; called at import and via /reload."""
    global _fixed_df, _user_df
    f = _norm(pd.read_csv(FIXED_CSV))
    u = _norm(pd.read_csv(USER_CSV))

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

# ---- accessors used by routers ----
def fixed_df() -> pd.DataFrame:
    return _fixed_df

def user_df() -> pd.DataFrame:
    return _user_df

# ---- helpers ----
FIXED_TOTAL_DM = 1000.0

def _add_row(totals: Dict[str, float], dm: float, row: pd.Series):
    totals["Protein"] += float(row["protein_g"]) * dm / 100.0
    totals["Fat"]     += float(row["fat_g"])     * dm / 100.0
    totals["CHO"]     += float(row["cho_g"])     * dm / 100.0
    totals["Fiber"]   += float(row["fiber_g"])   * dm / 100.0
    totals["Ash"]     += float(row["ash_g"])     * dm / 100.0
    totals["Ca"]      += float(row["calcium_mg"])    * dm / 100.0 / 1000.0
    totals["P"]       += float(row["phosphorus_mg"]) * dm / 100.0 / 1000.0
    totals["Iron"]    += float(row["iron_mg"])       * dm / 100.0 / 100.0
    totals["Energy"]  += float(row["energy_kcal"])   * dm / 100.0

def _row_name(x) -> str:
    try:
        if isinstance(x, dict):
            return str(x.get("ingredient") or x.get("ingredient_name", "")).strip().lower()
        if isinstance(x, pd.Series):
            return str(x.get("ingredient_name", "")).strip().lower()
    except Exception:
        pass
    return str(x).strip().lower()

def _compress_breakdown(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Combine multiple entries for the same ingredient into one line."""
    agg = defaultdict(lambda: {"ingredient": "", "dm_g": 0.0, "fixed": False})
    for row in raw:
        name = row["ingredient"]
        agg[name]["ingredient"] = name
        agg[name]["dm_g"] = round(agg[name]["dm_g"] + float(row["dm_g"]), 2)
        agg[name]["fixed"] = agg[name]["fixed"] or bool(row.get("fixed", False))
    merged = list(agg.values())
    merged.sort(key=lambda r: (not r["fixed"], r["ingredient"].lower()))
    return merged

# ---- main calculator ----
def calculate_diet(selected_names: List[str]) -> Dict[str, Any]:
    fdf = fixed_df()
    udf = user_df()

    # ---------- gather fixed ----------
    dm_breakdown_raw: List[Dict[str, Any]] = []
    ingredient_totals: List[Dict[str, Any]] = []
    totals = {k: 0.0 for k in ["Protein","Fat","CHO","Fiber","Ash","Ca","P","Iron","Energy"]}

    fixed_dm_used = 0.0
    for _, r in fdf.iterrows():
        dm = float(r["dm_g"])
        if dm <= 0:
            # skip fixed lines with 0 DM so they never show as 0 in the table
            continue
        _add_row(totals, dm, r)
        dm_breakdown_raw.append({"ingredient": r["ingredient_name"], "dm_g": round(dm,2), "fixed": True})
        ingredient_totals.append({
            "ingredient": r["ingredient_name"], "dm_g": round(dm,2),
            "protein_g": round(float(r["protein_g"]) * dm / 100.0, 2),
            "fat_g": round(float(r["fat_g"]) * dm / 100.0, 2),
            "cho_g": round(float(r["cho_g"]) * dm / 100.0, 2),
            "fiber_g": round(float(r["fiber_g"]) * dm / 100.0, 2),
            "ash_g": round(float(r["ash_g"]) * dm / 100.0, 2),
            "ca_mg": round(float(r["calcium_mg"]) * dm / 100.0, 2),
            "p_mg": round(float(r["phosphorus_mg"]) * dm / 100.0, 2),
            "iron_mg": round(float(r["iron_mg"]) * dm / 100.0, 2),
            "energy_kcal": round(float(r["energy_kcal"]) * dm / 100.0, 2),
            "fixed": True
        })
        fixed_dm_used += dm

    remaining = max(0.0, FIXED_TOTAL_DM - fixed_dm_used)

    # ---------- selected rows (unique, case-insensitive) ----------
    seen = set()
    picks: List[pd.Series] = []
    for name in selected_names:
        key = name.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        r = udf[udf["ingredient_name"].str.lower() == key]
        if not r.empty:
            picks.append(r.iloc[0])

    def gname(s: pd.Series) -> str:
        return str(s.get("group_name", "")).strip().lower()

    # classify groups
    meats_a = [r for r in picks if "meat group a" in gname(r)]
    meats_b = [r for r in picks if "meat group b" in gname(r)]
    meats_c = [r for r in picks if "meat group c" in gname(r)]
    grains_a = [r for r in picks if "grain a" in gname(r)]
    grains_b = [r for r in picks if "grain b" in gname(r)]
    veg_a    = [r for r in picks if "vegetable a" in gname(r)]
    veg_b    = [r for r in picks if "vegetable b" in gname(r)]
    veg_c    = [r for r in picks if "vegetable c" in gname(r)]
    oils     = [r for r in picks if "oil" in gname(r)]
    fruits   = [r for r in picks if "fruit" in gname(r)]
    organs   = [r for r in picks if "organ" in gname(r) and "liver" not in str(r["ingredient_name"]).lower()]
    livers   = [r for r in picks if "liver" in str(r["ingredient_name"]).lower()]

    issues: List[str] = []

    # add_item merges nutrient totals and merges the *table* row for the same ingredient
    def add_item(r: pd.Series, dm: float):
        nonlocal remaining
        if dm <= 0 or remaining <= 0:
            return 0.0
        dm = min(dm, remaining)
        name = r["ingredient_name"]

        _add_row(totals, dm, r)
        dm_breakdown_raw.append({"ingredient": name, "dm_g": round(dm, 2), "fixed": False})

        # merge into ingredient_totals
        for item in ingredient_totals:
            if item.get("ingredient") == name and not item.get("fixed", False):
                item["dm_g"]        = round(item["dm_g"] + dm, 2)
                item["protein_g"]   = round(item["protein_g"]   + float(r["protein_g"])   * dm / 100.0, 2)
                item["fat_g"]       = round(item["fat_g"]       + float(r["fat_g"])       * dm / 100.0, 2)
                item["cho_g"]       = round(item["cho_g"]       + float(r["cho_g"])       * dm / 100.0, 2)
                item["fiber_g"]     = round(item["fiber_g"]     + float(r["fiber_g"])     * dm / 100.0, 2)
                item["ash_g"]       = round(item["ash_g"]       + float(r["ash_g"])       * dm / 100.0, 2)
                item["ca_mg"]       = round(item["ca_mg"]       + float(r["calcium_mg"])  * dm / 100.0, 2)
                item["p_mg"]        = round(item["p_mg"]        + float(r["phosphorus_mg"]) * dm / 100.0, 2)
                item["iron_mg"]     = round(item["iron_mg"]     + float(r["iron_mg"])     * dm / 100.0, 2)
                item["energy_kcal"] = round(item["energy_kcal"] + float(r["energy_kcal"]) * dm / 100.0, 2)
                remaining -= dm
                return dm

        ingredient_totals.append({
            "ingredient": name,
            "dm_g": round(dm, 2),
            "protein_g":   round(float(r["protein_g"])   * dm / 100.0, 2),
            "fat_g":       round(float(r["fat_g"])       * dm / 100.0, 2),
            "cho_g":       round(float(r["cho_g"])       * dm / 100.0, 2),
            "fiber_g":     round(float(r["fiber_g"])     * dm / 100.0, 2),
            "ash_g":       round(float(r["ash_g"])       * dm / 100.0, 2),
            "ca_mg":       round(float(r["calcium_mg"])  * dm / 100.0, 2),
            "p_mg":        round(float(r["phosphorus_mg"]) * dm / 100.0, 2),
            "iron_mg":     round(float(r["iron_mg"])     * dm / 100.0, 2),
            "energy_kcal": round(float(r["energy_kcal"]) * dm / 100.0, 2),
        })
        remaining -= dm
        return dm

    def split_even(rows: List[pd.Series], total_dm: float) -> float:
        if not rows or total_dm <= 0:
            return 0.0
        total_dm = min(total_dm, remaining)
        each = round(total_dm / len(rows), 2)
        used = 0.0
        for i, r in enumerate(rows):
            dm = each if i < len(rows) - 1 else round(total_dm - each * (len(rows) - 1), 2)
            used += add_item(r, dm)
        return used

    def choose_grains_for_use(grains_a_rows, grains_b_rows):
        # prefer one A + one B; else two A; else one B
        chosen_a, chosen_b = [], []
        if grains_a_rows and grains_b_rows:
            chosen_a = grains_a_rows[:1]
            chosen_b = grains_b_rows[:1]
        elif grains_a_rows:
            chosen_a = grains_a_rows[:2]
        elif grains_b_rows:
            chosen_b = grains_b_rows[:1]
        return chosen_a, chosen_b

    def allocate_weighted(
        rows: List[pd.Series],
        total_dm: float,
        *,
        weight_key: str,
        inverse: bool = False
    ) -> float:
        """
        Distribute total_dm across rows by a nutrient key.
        - weight_key is a per-100g CSV column (e.g., 'cho_g', 'energy_kcal', 'fiber_g').
        - inverse=True gives LESS share to rows with higher values (useful to discourage high fiber).
        """
        if not rows or total_dm <= 0:
            return 0.0

        budget = min(total_dm, remaining)
        if budget <= 0:
            return 0.0

        wts = []
        for r in rows:
            try:
                val = max(float(r[weight_key]), 0.0)
            except Exception:
                val = 0.0
            wts.append((1.0 / (val + 1e-9)) if inverse else val)

        s = sum(wts)
        used = 0.0
        n = len(rows)

        if s <= 0:
            each = round(budget / n, 2)
            for i, r in enumerate(rows):
                dm = each if i < n - 1 else round(budget - each * (n - 1), 2)
                used += add_item(r, dm)
            return used

        for i, r in enumerate(rows):
            share = wts[i] / s
            dm = round(budget * share, 2)
            if i == n - 1:
                dm = round(budget - used, 2)
            used += add_item(r, dm)
        return used

    # ---------- 1) Organs (hard limits) ----------
    LIVER_MIN     = 100.0   # never below 100 g
    OTHER_ORG_MAX = 50.0    # all non-liver organs together ≤ 50 g
    ORG_TOTAL_MAX = 150.0   # liver + other organs ≤ 150 g

    if livers:
        add_item(livers[0], LIVER_MIN)
    else:
        issues.append("Liver is mandatory (≥100 g). Please select a liver.")

    if organs:
        split_even(organs, min(OTHER_ORG_MAX, remaining))

    # ---------- 2) Oils ----------
    if oils:
        split_even(oils, min(10.0, remaining))  # ≤10 g total

    # ---------- 3) Vegetables ----------
    VEG_AB_MAX = 150.0
    VEG_B_MAX  = 70.0
    VEG_A_MIN_IF_B0 = 80.0

    veg_a_use = veg_a[:2]
    veg_b_use = veg_b[:2]

    if veg_b and not veg_a:
        issues.append("Vegetable B selected; add at least one Vegetable A.")

    used_veg_b = allocate_weighted(
        veg_b_use, min(VEG_B_MAX, remaining),
        weight_key="fiber_g", inverse=True
    )

    if veg_a_use:
        a_min  = VEG_A_MIN_IF_B0 if veg_a_use and not veg_b_use else 0.0
        a_room = max(0.0, min(VEG_AB_MAX - used_veg_b, remaining))
        target_a = max(a_min, a_room)
        allocate_weighted(veg_a_use, target_a, weight_key="energy_kcal", inverse=False)

    # potato (veg C) optional
    split_even(veg_c, min(100.0, remaining))  # potato cap 100 g if present

    # ---------- 4) Grains ----------
    grain_min = 300.0     # ALWAYS >= 300 g (A+B)
    grain_max = 400.0
    GRAIN_B_TARGET = 200.0  # also the cap
    GRAIN_A_ITEM_CAP = 150.0

    grains_a_use, grains_b_use = choose_grains_for_use(grains_a, grains_b)
    grains_selected = grains_a_use + grains_b_use

    if grains_selected:
        # A) allocate Grain B up to EXACTLY 200 g (or as much as possible up to that cap)
        used_b = allocate_weighted(
            grains_b_use,
            min(GRAIN_B_TARGET, remaining),
            weight_key="fiber_g",
            inverse=True
        )

        # If we had A already added earlier that stole budget, we may still be <200.
        # Try to top B to 200 by shaving from A room later (the guards will rebalance too).

        # B) ensure total grains reach at least 300 using A
        needed_for_min = max(0.0, grain_min - used_b)
        used_a = allocate_weighted(
            grains_a_use,
            min(needed_for_min, remaining),
            weight_key="cho_g",
            inverse=False
        )

        # C) Fill remaining room to grain_max with A (B is fixed at ≤200)
        grain_used_total = used_b + used_a
        room = max(0.0, min(grain_max - grain_used_total, remaining))
        if room > 0:
            if grains_a_use:
                allocate_weighted(grains_a_use, room, weight_key="cho_g", inverse=False)
            else:
                # only B exists → headroom up to 200
                b_head = max(0.0, GRAIN_B_TARGET - used_b)
                if b_head > 0:
                    allocate_weighted(grains_b_use, min(room, b_head), weight_key="fiber_g", inverse=True)
        if grains_b and not grains_a:
            issues.append("Grain B selected without Grain A; add a Grain A (B ≤ 200 g).")
    else:
        issues.append("Choose at least one grain (max two total).")

    # Grain A single-item cap rebalancer
    grains_a_set = {r["ingredient_name"].strip().lower() for r in grains_a}
    grains_b_set = {r["ingredient_name"].strip().lower() for r in grains_b}

    def _rows_of(name_set):
        return [x for x in ingredient_totals if x["ingredient"].strip().lower() in name_set and not x.get("fixed")]

    def _sum_dm(name_set):
        return round(sum(x["dm_g"] for x in _rows_of(name_set)), 2)

    a_rows_now = _rows_of(grains_a_set)
    b_rows_now = _rows_of(grains_b_set)
    if a_rows_now:
        for it in sorted(a_rows_now, key=lambda r: r["dm_g"], reverse=True):
            if it["dm_g"] > GRAIN_A_ITEM_CAP + 1e-9:
                excess = round(it["dm_g"] - GRAIN_A_ITEM_CAP, 2)
                # move to B first (up to 200)
                b_dm = _sum_dm(grains_b_set)
                b_headroom = max(0.0, GRAIN_B_TARGET - b_dm)
                to_b = round(min(excess, b_headroom), 2)
                if to_b > 0 and b_rows_now:
                    # remove from A
                    baseA = max(it["dm_g"], 1e-9)
                    scaleA = (baseA - to_b) / baseA
                    for k in ["protein_g","fat_g","cho_g","fiber_g","ash_g","ca_mg","p_mg","iron_mg","energy_kcal"]:
                        it[k] = round(it[k] * scaleA, 2)
                    it["dm_g"] = round(baseA - to_b, 2)
                    # add to first B
                    b0 = b_rows_now[0]
                    baseB = max(b0["dm_g"], 1e-9)
                    for k in ["protein_g","fat_g","cho_g","fiber_g","ash_g","ca_mg","p_mg","iron_mg","energy_kcal"]:
                        per_g = b0[k] / baseB if baseB else 0.0
                        b0[k] = round(b0[k] + per_g * to_b, 2)
                    b0["dm_g"] = round(b0["dm_g"] + to_b, 2)
                    excess = round(excess - to_b, 2)

                # then spread to other A items up to 150
                if excess > 0 and len(a_rows_now) > 1:
                    others = [r for r in a_rows_now if r is not it and r["dm_g"] < GRAIN_A_ITEM_CAP - 1e-9]
                    for r in sorted(others, key=lambda r: r["dm_g"]):
                        if excess <= 0:
                            break
                        room = round(GRAIN_A_ITEM_CAP - r["dm_g"], 2)
                        add = round(min(room, excess), 2)
                        if add > 0:
                            # remove from 'it'
                            baseA = max(it["dm_g"], 1e-9)
                            scaleA = (baseA - add) / baseA
                            for k in ["protein_g","fat_g","cho_g","fiber_g","ash_g","ca_mg","p_mg","iron_mg","energy_kcal"]:
                                it[k] = round(it[k] * scaleA, 2)
                            it["dm_g"] = round(baseA - add, 2)
                            # add to 'r'
                            baseR = max(r["dm_g"], 1e-9)
                            for k in ["protein_g","fat_g","cho_g","fiber_g","ash_g","ca_mg","p_mg","iron_mg","energy_kcal"]:
                                per_g = r[k] / baseR if baseR else 0.0
                                r[k] = round(r[k] + per_g * add, 2)
                            r["dm_g"] = round(baseR + add, 2)
                            excess = round(excess - add, 2)

                if excess > 0:
                    issues.append("A Grain A item exceeded 150 g; limited redistribution available (consider adding Grain B/another Grain A).")

    # ---------- 5) Meat ----------
    def choose_meats() -> List[pd.Series]:
        # prefer A + B, else A + (C or B), else B + (A or C), else C + C
        if meats_a and meats_b:
            return [meats_a[0], meats_b[0]]
        if meats_a:
            return meats_a[:2] if len(meats_a) > 1 else [meats_a[0]] + (meats_c[:1] or meats_b[:1])
        if meats_b:
            return [meats_b[0]] + (meats_a[:1] or meats_c[:1])
        if meats_c:
            return meats_c[:2]
        return []

    meats_selected = choose_meats()
    meat_target = 280.0
    meat_target = max(200.0, min(350.0, meat_target))  # clamp 200–350, target ~280

    if meats_b and not meats_a:
        issues.append("High-fat meat (Group B) selected; add a Group A meat as well.")

    def fat_pct_if(dm_alloc: List[Tuple[pd.Series, float]]) -> float:
        tot_dm = sum(dm for _, dm in dm_alloc) or 1.0
        tot_fat = sum(float(r["fat_g"]) * dm / 100.0 for r, dm in dm_alloc)
        return (tot_fat / tot_dm) * 100.0

    if meats_selected:
        each = round(min(meat_target, remaining) / len(meats_selected), 2)
        alloc: List[Tuple[pd.Series, float]] = [
            (r, each if i < len(meats_selected)-1 else round(min(meat_target, remaining) - each*(len(meats_selected)-1), 2))
            for i, r in enumerate(meats_selected)
        ]
        def _key(s: pd.Series) -> str:
            return str(s["ingredient_name"]).strip().lower()
        meats_c_keys = {_key(r) for r in meats_c}
        if all(_key(r) in meats_c_keys for r in meats_selected):
            if fat_pct_if(alloc) > 16.0:
                issues.append("Group C only exceeds 16% fat; add a Group A meat or reduce C share.")

        meats_a_names = {_row_name(r) for r in meats_a}
        if meats_a_names and any(_row_name(r) not in meats_a_names for r in meats_selected):
            a_rows = [r for r in meats_selected if _row_name(r) in meats_a_names]
            if a_rows:
                a_cap = 150.0
                a_each = round(min(a_cap, remaining) / len(a_rows), 2)
                new_alloc: List[Tuple[pd.Series, float]] = []
                used_a_total = 0.0
                for r in meats_selected:
                    if _row_name(r) in meats_a_names:
                        dm = a_each
                        used_a_total += dm
                    else:
                        dm = 0.0
                    new_alloc.append((r, dm))
                rest = max(0.0, min(meat_target, remaining) - used_a_total)
                others_idx = [i for i, (r, _) in enumerate(new_alloc) if _row_name(r) not in meats_a_names]
                if others_idx:
                    per = round(rest / len(others_idx), 2)
                    for j, idx in enumerate(others_idx):
                        dm = per if j < len(others_idx) - 1 else round(rest - per * (len(others_idx) - 1), 2)
                        r0, prev = new_alloc[idx]
                        new_alloc[idx] = (r0, prev + dm)
                alloc = new_alloc

        for r, dm in alloc:
            add_item(r, dm)

    # ---------- 6) Fruits (optional 15–25 g) ----------
    if fruits:
        split_even(fruits, min(25.0, remaining))

    # ---------- PRE-TUNING SUMMARY ----------
    def recalc_totals_from_table(rows):
        t = {k:0.0 for k in ["Protein","Fat","CHO","Fiber","Ash","Ca","P","Iron","Energy"]}
        for it in rows:
            t["Protein"] += it["protein_g"]
            t["Fat"]     += it["fat_g"]
            t["CHO"]     += it["cho_g"]
            t["Fiber"]   += it["fiber_g"]
            t["Ash"]     += it["ash_g"]
            t["Ca"]      += it["ca_mg"]/1000.0
            t["P"]       += it["p_mg"]/1000.0
            t["Iron"]    += it["iron_mg"]/100.0
            t["Energy"]  += it["energy_kcal"]
        return t

    def table_pct(key): return totals[key] * 100.0 / FIXED_TOTAL_DM

    def shrink_item_dm(it, delta):
        base = it["dm_g"]
        if base <= 0 or delta <= 0:
            return False
        delta = min(delta, base)
        scale = (base - delta) / base if base else 1.0
        for k in ["protein_g","fat_g","cho_g","fiber_g","ash_g","ca_mg","p_mg","iron_mg","energy_kcal"]:
            it[k] = round(it[k] * scale, 2)
        it["dm_g"] = round(base - delta, 2)
        return True

    def grow_item_dm(it, delta: float):
        if delta <= 0:
            return False
        base = max(it["dm_g"], 1e-9)
        scale = (base + delta) / base
        for k in ["protein_g","fat_g","cho_g","fiber_g","ash_g","ca_mg","p_mg","iron_mg","energy_kcal"]:
            it[k] = round(it[k] * scale, 2)
        it["dm_g"] = round(base + delta, 2)
        return True

    def _refresh_totals():
        new = recalc_totals_from_table(ingredient_totals)
        for k in totals:
            totals[k] = new[k]

    meats_a_set = {r["ingredient_name"].strip().lower() for r in meats_a}
    meats_b_set = {r["ingredient_name"].strip().lower() for r in meats_b}
    meats_c_set = {r["ingredient_name"].strip().lower() for r in meats_c}
    grains_set  = grains_a_set | grains_b_set
    vegc_set    = {r["ingredient_name"].strip().lower() for r in veg_c}

    def is_meat_a(it): return it["ingredient"].strip().lower() in meats_a_set
    def is_meat_c(it): return it["ingredient"].strip().lower() in meats_c_set
    def is_grain(it):  return it["ingredient"].strip().lower() in grains_set
    def is_veg_c(it):  return it["ingredient"].strip().lower() in vegc_set

    # --- FAT (12–17%) baseline adjust ---
    FAT_MIN, FAT_MAX = 12.0, 17.0
    fat_pct = table_pct("Fat")

    b_names = meats_b_set
    c_names = meats_c_set

    if fat_pct > FAT_MAX:
        for chooser in (
            lambda x: x["ingredient"].strip().lower() in b_names,
            lambda x: x["ingredient"].strip().lower() in c_names,
        ):
            for it in [x for x in ingredient_totals if not x.get("fixed") and chooser(x)]:
                if fat_pct <= FAT_MAX:
                    break
                if shrink_item_dm(it, 10.0):
                    issues.append(f"Fat > {FAT_MAX}% → reduced {it['ingredient']} by 10 g.")
                    totals = recalc_totals_from_table(ingredient_totals)
                    fat_pct = table_pct("Fat")

    if fat_pct > FAT_MAX:
        oil_names = {r["ingredient_name"].strip().lower() for r in oils}
        for it in [x for x in ingredient_totals if not x.get("fixed") and x["ingredient"].strip().lower() in oil_names]:
            if fat_pct <= FAT_MAX:
                break
            if shrink_item_dm(it, 10.0):
                issues.append(f"Fat > {FAT_MAX}% → reduced oil {it['ingredient']} by 10 g.")
                totals = recalc_totals_from_table(ingredient_totals)
                fat_pct = table_pct("Fat")

    if fat_pct < FAT_MIN:
        co = next((x for x in ingredient_totals if x["ingredient"].lower()=="coconut oil"), None)
        if co:
            add = 10.0
            base = max(co["dm_g"], 1e-9)
            for k in ["protein_g","fat_g","cho_g","fiber_g","ash_g","ca_mg","p_mg","iron_mg","energy_kcal"]:
                per_g = co[k] / base
                co[k] = round(co[k] + per_g*add, 2)
            co["dm_g"] = round(co["dm_g"] + add, 2)
            issues.append("Fat < 12% → added 10 g coconut oil.")
            totals = recalc_totals_from_table(ingredient_totals)

    # --- PROTEIN cap (≤ 42%) ---
    liver_names  = {r["ingredient_name"].strip().lower() for r in livers}

    def total_meat_dm_now():
        meat_names = {r["ingredient_name"].strip().lower() for r in (meats_a+meats_b+meats_c)}
        return sum(x["dm_g"] for x in ingredient_totals if x["ingredient"].strip().lower() in meat_names)

    while table_pct("Protein") > 42.0:
        changed = False
        for it in [x for x in ingredient_totals if x["ingredient"].strip().lower() in meats_a_set]:
            if it["dm_g"] <= 0:
                continue
            if shrink_item_dm(it, 10.0):
                issues.append("Protein > 42% → reduced Group A meat by 10 g.")
                totals = recalc_totals_from_table(ingredient_totals)
                changed = True
                if table_pct("Protein") < 41.0:
                    break
        if table_pct("Protein") <= 42.0 or changed:
            if table_pct("Protein") <= 42.0:
                break

        if total_meat_dm_now() < 200.0:
            break

        for it in [x for x in ingredient_totals if x["ingredient"].strip().lower() in liver_names]:
            if it["dm_g"] <= 120.0:
                continue
            cut = min(10.0, it["dm_g"] - 120.0)
            if shrink_item_dm(it, cut):
                issues.append(f"Protein > 42% → reduced liver by {cut:.0f} g (not below 120 g).")
                totals = recalc_totals_from_table(ingredient_totals)
                if table_pct("Protein") <= 42.0:
                    break
        else:
            break

    # --- FIBER (3–6%) ---
    FIBER_MIN, FIBER_MAX = 3.0, 6.0
    veg_names = {r["ingredient_name"].strip().lower() for r in (veg_a+veg_b+veg_c)}
    def veg_rows():
        return [x for x in ingredient_totals if x["ingredient"].strip().lower() in veg_names]

    def reduce_veg_by(total_cut):
        cut_left = total_cut
        for it in veg_rows():
            if cut_left <= 0:
                break
            cut = min(10.0, it["dm_g"], cut_left)
            if shrink_item_dm(it, cut):
                cut_left -= cut
                issues.append(f"Fiber > 6% → reduced {it['ingredient']} by {cut:.0f} g.")

    def add_psyllium(add=10.0):
        psy = next((x for x in ingredient_totals if x["ingredient"].lower()=="psyllium husk"), None)
        if not psy:
            return
        base = max(psy["dm_g"], 1e-9)
        add = min(add, 15.0)
        for k in ["protein_g","fat_g","cho_g","fiber_g","ash_g","ca_mg","p_mg","iron_mg","energy_kcal"]:
            per_g = psy[k]/base
            psy[k] = round(psy[k] + per_g*add, 2)
        psy["dm_g"] = round(psy["dm_g"] + add, 2)
        issues.append("Fiber < 3% → added 10 g psyllium husk.")

    fiber_pct = table_pct("Fiber")
    while fiber_pct > FIBER_MAX:
        reduce_veg_by(10.0)
        totals = recalc_totals_from_table(ingredient_totals)
        fiber_pct = table_pct("Fiber")
        if fiber_pct <= FIBER_MAX:
            break

    if fiber_pct < FIBER_MIN:
        add_psyllium(10.0)
        totals = recalc_totals_from_table(ingredient_totals)

    # --- PROTEIN raise if below 32% ---
    PRO_MIN = 32.0
    if table_pct("Protein") < PRO_MIN:
        budget = 120.0
        for pred in (is_meat_a, is_meat_c):
            for it in [x for x in ingredient_totals if pred(x)]:
                if table_pct("Protein") >= PRO_MIN or budget <= 0:
                    break
                step = min(10.0, budget)
                if grow_item_dm(it, step):
                    budget -= step
                    issues.append(f"Protein < {PRO_MIN}% → increased {it['ingredient']} by {step:.0f} g.")
                    _refresh_totals()
            if table_pct("Protein") >= PRO_MIN or budget <= 0:
                break
        if table_pct("Protein") < PRO_MIN and budget > 0:
            for pred in (is_grain, is_veg_c):
                for it in [x for x in ingredient_totals if pred(it)]:
                    if table_pct("Protein") >= PRO_MIN or budget <= 0:
                        break
                    if shrink_item_dm(it, 10.0):
                        budget -= 10.0
                        issues.append(f"Protein < {PRO_MIN}% → reduced {it['ingredient']} by 10 g to raise concentration.")
                        _refresh_totals()

    # --- Normalizers/guards ---
    def grains_dm_total():
        return round(sum(x["dm_g"] for x in ingredient_totals if is_grain(x)), 2)

    def topup_or_trim_without_fiber(dm_gap_value: float):
        PRO_MIN_LOC = 32.0
        grains_at_cap = grains_dm_total() >= grain_max - 1e-9
        p = table_pct("Protein")
        meat_pool  = [x for x in ingredient_totals if (is_meat_a(x) or is_meat_c(x))]
        grain_pool = [] if grains_at_cap else [x for x in ingredient_totals if is_grain(x)]

        if p < PRO_MIN_LOC:
            pool = meat_pool + grain_pool
        else:
            pool = grain_pool[:]
            if not pool:
                pool = [x for x in ingredient_totals
                        if (not x.get("fixed")
                            and not is_meat_a(x) and not is_meat_c(x)
                            and not is_grain(x)
                            and x["ingredient"].strip().lower() not in {"psyllium husk"})]

        if not pool:
            pool = [x for x in ingredient_totals if not x.get("fixed")]
            if not pool:
                return

        per = round(abs(dm_gap_value) / len(pool), 2)
        for i, it in enumerate(pool):
            step = per if i < len(pool)-1 else round(abs(dm_gap_value) - per*(len(pool)-1), 2)
            if dm_gap_value > 0:
                grow_item_dm(it, step)
            else:
                shrink_item_dm(it, step)

        issues.append(f"Normalized DM to {FIXED_TOTAL_DM} g (no veg; meats only if Protein < {PRO_MIN_LOC}%).")
        _refresh_totals()

    def grain_guard():
        def grain_rows():
            return [x for x in ingredient_totals if is_grain(x)]
        def grains_dm_total_local():
            return round(sum(x["dm_g"] for x in grain_rows()), 2)

        # Cap at grain_max
        gdm = grains_dm_total_local()
        if gdm > grain_max:
            over = round(gdm - grain_max, 2)
            rows = grain_rows()
            rows.sort(key=lambda it: (it["cho_g"] / max(it["dm_g"], 1e-9)), reverse=True)
            left = over
            while left > 0 and rows:
                for it in rows:
                    if left <= 0:
                        break
                    cut = min(5.0, it["dm_g"], left)
                    if shrink_item_dm(it, cut):
                        left = round(left - cut, 2)
            if over > left:
                issues.append(f"Grains > {grain_max} g → reduced grains by {int(over-left)} g.")
            _refresh_totals()

        # Floor at grain_min
        gdm = grains_dm_total_local()
        if gdm < grain_min:
            need = round(grain_min - gdm, 2)
            rows = grain_rows()
            if rows:
                per = round(need / len(rows), 2)
                added = 0.0
                for i, it in enumerate(rows):
                    step = per if i < len(rows) - 1 else round(need - per * (len(rows) - 1), 2)
                    if step > 0 and grow_item_dm(it, step):
                        added += step
                if added > 0:
                    issues.append(f"Grains < {grain_min} g → increased grains by {int(added)} g.")
                _refresh_totals()

    def grain_guard_strict():
        """Same as grain_guard but always floors at 300 g exactly."""
        nonlocal grain_min
        prev = grain_min
        grain_min = 300.0
        grain_guard()
        grain_min = prev

    def organ_guard():
        LIVER_MIN_LOC     = 100.0
        OTHER_ORG_MAX_LOC = 50.0
        ORG_TOTAL_MAX_LOC = 150.0

        liver_set = {r["ingredient_name"].strip().lower() for r in livers}
        other_set = {r["ingredient_name"].strip().lower() for r in organs}

        liver_rows = [x for x in ingredient_totals if x["ingredient"].strip().lower() in liver_set]
        other_rows = [x for x in ingredient_totals if x["ingredient"].strip().lower() in other_set]
        if not liver_rows:
            return

        liver = liver_rows[0]
        changed = False

        for it in other_rows:
            if it["dm_g"] > OTHER_ORG_MAX_LOC + 1e-9:
                cut = round(it["dm_g"] - OTHER_ORG_MAX_LOC, 2)
                if shrink_item_dm(it, cut):
                    issues.append(f"Organ > {OTHER_ORG_MAX_LOC:.0f} g → reduced {it['ingredient']} by {int(round(cut))} g.")
                    changed = True

        if liver["dm_g"] < LIVER_MIN_LOC - 1e-9:
            need = round(LIVER_MIN_LOC - liver["dm_g"], 2)
            if grow_item_dm(liver, need):
                issues.append(f"Raised liver by {int(round(need))} g to reach {LIVER_MIN_LOC:.0f} g.")
                changed = True

        cur_liver = round(liver["dm_g"], 2)
        cur_other = round(sum(x["dm_g"] for x in other_rows), 2)
        cur_total = round(cur_liver + cur_other, 2)

        if cur_total > ORG_TOTAL_MAX_LOC + 1e-9:
            left = round(cur_total - ORG_TOTAL_MAX_LOC, 2)
            i = 0
            while left > 0 and other_rows and any(r["dm_g"] > 0 for r in other_rows):
                it = other_rows[i % len(other_rows)]
                cut = min(10.0, it["dm_g"], left)
                if cut >= 1e-9 and shrink_item_dm(it, cut):
                    left = round(left - cut, 2)
                    changed = True
                i += 1
            if left > 0:
                can_cut = max(0.0, liver["dm_g"] - LIVER_MIN_LOC)
                cut = min(left, can_cut)
                if cut >= 1e-9 and shrink_item_dm(liver, cut):
                    left = round(left - cut, 2)
                    changed = True
            reduced = (cur_total - ORG_TOTAL_MAX_LOC) - left
            if reduced > 1e-9:
                issues.append(
                    f"Organs > {ORG_TOTAL_MAX_LOC:.0f} g → reduced by {int(round(reduced))} g (liver ≥ {LIVER_MIN_LOC:.0f} g)."
                )
        if changed:
            _refresh_totals()
    def vegetable_guard():
        """
        Enforce Veg A + Veg B combined >= 150 g.
        Prefer to fund from grains (keeping grain floor 300 g), then from meats if needed.
        Add grams to Veg A first (if present), then Veg B.
        """
        VEG_TOTAL_MIN = 150.0
        GRAIN_FLOOR = 300.0

        vegA_set = {r["ingredient_name"].strip().lower() for r in veg_a}
        vegB_set = {r["ingredient_name"].strip().lower() for r in veg_b}
        vegAB_set = vegA_set | vegB_set

        def rows_for(name_set):
            return [x for x in ingredient_totals
                    if x["ingredient"].strip().lower() in name_set and not x.get("fixed")]

        def grams(name_set):
            return round(sum(x["dm_g"] for x in rows_for(name_set)), 2)

        def grains_now():
            return round(sum(x["dm_g"] for x in ingredient_totals
                            if x["ingredient"].strip().lower() in (grains_a_set | grains_b_set)), 2)

    # small local helper to free grams, first from Grain B, then Grain A (never below 300 g total)
        def trim_from_grains(left):
            freed = 0.0
            for name_set in (grains_b_set, grains_a_set):
                rows = [x for x in ingredient_totals if x["ingredient"].strip().lower() in name_set]
                rows.sort(key=lambda r: r["dm_g"], reverse=True)
                for it in rows:
                    if left <= 0:
                        break
                    spare = max(0.0, grains_now() - GRAIN_FLOOR)
                    if spare <= 0:
                        break
                    cut = min(10.0, it["dm_g"], left, spare)
                    if cut > 0 and shrink_item_dm(it, cut):
                        left = round(left - cut, 2)
                        freed = round(freed + cut, 2)
                        _refresh_totals()
                if left <= 0:
                    break
            return freed, left

        veg_total = grams(vegAB_set)
        if veg_total >= VEG_TOTAL_MIN - 1e-9:
            return  # already okay

        need = round(VEG_TOTAL_MIN - veg_total, 2)

    # 1) try to free from grains
        freed, left = trim_from_grains(need)
        remaining_need = round(need - freed, 2)

    # 2) if still short, free from meats (prefer Group C, then B above its minimum share, then A above its minimum)
        if remaining_need > 0:
        # candidate pools, largest-first
            meatC_rows = [x for x in ingredient_totals if x["ingredient"].strip().lower() in meats_c_set]
            meatB_rows = [x for x in ingredient_totals if x["ingredient"].strip().lower() in meats_b_set]
            meatA_rows = [x for x in ingredient_totals if x["ingredient"].strip().lower() in meats_a_set]
            pools = [meatC_rows, meatB_rows, meatA_rows]
            for pool in pools:
                pool.sort(key=lambda r: r["dm_g"], reverse=True)
                for it in pool:
                    if remaining_need <= 0:
                        break
                    cut = min(10.0, it["dm_g"], remaining_need)
                    if cut > 0 and shrink_item_dm(it, cut):
                        remaining_need = round(remaining_need - cut, 2)
                        _refresh_totals()
                if remaining_need <= 0:
                    break

    # 3) add grams to vegetables (prefer Veg A first)
        to_add = round(need - remaining_need, 2)
        if to_add > 0:
            vegA_rows = rows_for(vegA_set)
            vegB_rows = rows_for(vegB_set)
            targets = vegA_rows if vegA_rows else vegB_rows
            if targets:
                each = round(to_add / len(targets), 2)
                used = 0.0
                for i, it in enumerate(targets):
                    add = each if i < len(targets) - 1 else round(to_add - used, 2)
                    if add > 0 and grow_item_dm(it, add):
                        used = round(used + add, 2)
                issues.append(f"Raised vegetables to ≥ {VEG_TOTAL_MIN} g combined.")
                _refresh_totals()
            else:
            # no veg rows exist in the table yet (edge-case), add the first selected veg if present
                pass


    # --- ENFORCE MEAT RULES you requested ---
    def enforce_meat_rules():
        GRAIN_FLOOR = 300.0
        MEAT_A_MIN  = 150.0        # A >= 150 g (NOT exact)
        MEAT_AB_MIN = 200.0        # (A + B) >= 200 g when both present
        MEAT_B_MIN_IF_PRESENT = 50.0  # ensure B has a non-zero real share when A & B both selected
        MEAT_C_ONLY_TARGET = 300.0

        def rows_for(name_set):
            return [x for x in ingredient_totals
                    if x["ingredient"].strip().lower() in name_set and not x.get("fixed")]

        def grams(name_set):
            return round(sum(x["dm_g"] for x in rows_for(name_set)), 2)

        def grains_now():
            return round(sum(x["dm_g"] for x in ingredient_totals if is_grain(x)), 2)

        def trim_from_grains(left):
            """Free grams from grains (B first, then A), never dropping total grains below 300 g."""
            freed = 0.0
            for name_set in (grains_b_set, grains_a_set):
                rows = [x for x in ingredient_totals if x["ingredient"].strip().lower() in name_set]
                rows.sort(key=lambda r: r["dm_g"], reverse=True)
                for it in rows:
                    if left <= 0: break
                    spare = max(0.0, grains_now() - GRAIN_FLOOR)
                    if spare <= 0: break
                    cut = min(10.0, it["dm_g"], left, spare)
                    if cut > 0 and shrink_item_dm(it, cut):
                        left  = round(left - cut, 2)
                        freed = round(freed + cut, 2)
                        _refresh_totals()
                if left <= 0: break
            return freed, left

        a_rows = rows_for(meats_a_set)
        b_rows = rows_for(meats_b_set)
        c_rows = rows_for(meats_c_set)

        a_dm = grams(meats_a_set)
        b_dm = grams(meats_b_set)
        c_dm = grams(meats_c_set)

    # --- B without A: warn, but DO NOT zero B (respect user selection) ---
        if b_rows and not a_rows:
            issues.append("Meat Group B is selected without Meat A; please add a Meat A to meet rules.")
            _refresh_totals()

    # --- If A exists, force A >= 150g (not exact) ---
        if a_rows and a_dm < MEAT_A_MIN - 1e-9:
            need = round(MEAT_A_MIN - a_dm, 2)
            freed, left = trim_from_grains(need)
            remaining_need = round(need - freed, 2)

        # If still short, try to free from Meat C, then (as last resort) a bit from B
            if remaining_need > 0 and c_rows:
                c_sorted = sorted(c_rows, key=lambda r: r["dm_g"], reverse=True)
                for it in c_sorted:
                    if remaining_need <= 0: break
                    cut = min(10.0, it["dm_g"], remaining_need)
                    if cut > 0 and shrink_item_dm(it, cut):
                        remaining_need = round(remaining_need - cut, 2); _refresh_totals()

            if remaining_need > 0 and b_rows:
                b_sorted = sorted(b_rows, key=lambda r: r["dm_g"], reverse=True)
                for it in b_sorted:
                    if remaining_need <= 0: break
                    cut = min(10.0, it["dm_g"], remaining_need)
                    if cut > 0 and shrink_item_dm(it, cut):
                        remaining_need = round(remaining_need - cut, 2); _refresh_totals()

            add_actual = round(need - (freed + remaining_need), 2)
            if add_actual > 0:
                grow_item_dm(a_rows[0], add_actual)
                issues.append(f"Raised Meat A to ≥ {MEAT_A_MIN:.0f} g.")
                _refresh_totals()

    # refresh after possibly raising A
        a_dm = grams(meats_a_set)
        b_dm = grams(meats_b_set)

    # --- If A & B both present: enforce B has a real share and A+B ≥ 200g ---
        if a_rows and b_rows:
        # 1) Ensure B gets a non-zero real share (≥ 50 g)
            if b_dm < MEAT_B_MIN_IF_PRESENT - 1e-9:
                need_b = round(MEAT_B_MIN_IF_PRESENT - b_dm, 2)

            # Prefer taking from grains (respecting 300 g floor)
                freed, left = trim_from_grains(need_b)
                remaining_need = round(need_b - freed, 2)

            # If still short, try taking a bit from excess A above 150 (never drop A below 150)
                if remaining_need > 0 and a_dm > MEAT_A_MIN + 1e-9:
                    give = min(remaining_need, round(a_dm - MEAT_A_MIN, 2))
                    if give > 0:
                    # cut from A (largest row) and add to B (largest row)
                        a_sorted = sorted(a_rows, key=lambda r: r["dm_g"], reverse=True)
                        b_sorted = sorted(b_rows, key=lambda r: r["dm_g"], reverse=True)
                        cut_left = give
                        for it in a_sorted:
                            if cut_left <= 0: break
                            cut = min(10.0, it["dm_g"] - MEAT_A_MIN, cut_left) if len(a_sorted)==1 else min(10.0, it["dm_g"], cut_left)
                            cut = max(0.0, cut)
                            if cut > 0 and shrink_item_dm(it, cut):
                                grow_item_dm(b_sorted[0], cut)
                                cut_left = round(cut_left - cut, 2); _refresh_totals()
                        remaining_need = round(remaining_need - (give - cut_left), 2)

                if remaining_need > 0:
                    issues.append("Could not fully fund minimum share for Meat B without breaking other floors.")
                else:
                    issues.append(f"Ensured Meat B ≥ {MEAT_B_MIN_IF_PRESENT:.0f} g when A & B both selected.")
                    _refresh_totals()

        # 2) Ensure A + B ≥ 200 g
            a_dm = grams(meats_a_set); b_dm = grams(meats_b_set)
            if (a_dm + b_dm) < MEAT_AB_MIN - 1e-9:
                need = round(MEAT_AB_MIN - (a_dm + b_dm), 2)
            # Prefer to add to B (keeps B meaningful)
                freed, left = trim_from_grains(need)
                add = round(need - left, 2)
                if add > 0:
                # add to the biggest B row
                    b_big = sorted(b_rows, key=lambda r: r["dm_g"], reverse=True)[0]
                    grow_item_dm(b_big, add)
                if left > 0:
                    issues.append("Not enough headroom to reach A+B minimum without breaking Grain floor.")
                else:
                    issues.append(f"Raised A+B meat to ≥ {MEAT_AB_MIN:.0f} g (A ≥ {MEAT_A_MIN:.0f} g).")
                _refresh_totals()

    # --- Only C present → keep your original rule ---
        if (not a_rows) and (not b_rows) and rows_for(meats_c_set):
            target = MEAT_C_ONLY_TARGET
            meat_dm = grams(meats_c_set)
            if meat_dm < target - 1e-9:
                need = round(target - meat_dm, 2)
                freed, left = trim_from_grains(need)
                add = round(need - left, 2)
                if add > 0:
                    grow_item_dm(rows_for(meats_c_set)[0], add)
                issues.append(f"Only Meat C selected → set total meat to {target:.0f} g (trimmed grains).")
                _refresh_totals()
            elif meat_dm > target + 1e-9:
                to_cut = round(meat_dm - target, 2)
                c_sorted = sorted(rows_for(meats_c_set), key=lambda r: r["dm_g"], reverse=True)
                left = to_cut
                for it in c_sorted:
                    if left <= 0: break
                    cut = min(it["dm_g"], left)
                    if cut > 0 and shrink_item_dm(it, cut):
                        left = round(left - cut, 2); _refresh_totals()
                issues.append(f"Only Meat C selected → reduced total meat to {target:.0f} g.")


    # --- Normalize DM to exactly 1000 g, then guards ---
    dm_now = round(sum(x["dm_g"] for x in ingredient_totals), 2)
    dm_gap = round(FIXED_TOTAL_DM - dm_now, 2)
    if abs(dm_gap) >= 0.5:
        topup_or_trim_without_fiber(dm_gap)

    # Apply grain/organ/meat guards (order matters)
    grain_guard()
    organ_guard()
    enforce_meat_rules()
    vegetable_guard()

    # --- ENERGY guard (4000–4500 kcal) ---
    ENERGY_MIN, ENERGY_MAX = 4000.0, 4500.0
    def _pct(k): return totals[k] * 100.0 / FIXED_TOTAL_DM
    def energy_now(): return totals["Energy"]
    def energy_density(it):
        dm = max(it["dm_g"], 1e-9); return it["energy_kcal"] / dm

    oil_names = {r["ingredient_name"].strip().lower() for r in oils}
    bset = meats_b_set
    def rows_oils():   return [x for x in ingredient_totals if x["ingredient"].strip().lower() in oil_names]
    def rows_meat_b(): return [x for x in ingredient_totals if x["ingredient"].strip().lower() in bset]
    def rows_grains(): return [x for x in ingredient_totals if is_grain(x)]

    def renorm_dm():
        dm_now_local = round(sum(x["dm_g"] for x in ingredient_totals), 2)
        dm_gap_local = round(FIXED_TOTAL_DM - dm_now_local, 2)
        if abs(dm_gap_local) >= 0.5:
            topup_or_trim_without_fiber(dm_gap_local)
        else:
            new = recalc_totals_from_table(ingredient_totals)
            for k in totals: totals[k] = new[k]

    safety = 0
    while energy_now() > ENERGY_MAX and safety < 60:
        changed = False
        for it in rows_oils():
            if energy_now() <= ENERGY_MAX: break
            if it["dm_g"] > 0 and shrink_item_dm(it, 5.0):
                issues.append("Energy > 4500 → reduced oil by 5 g.")
                renorm_dm(); changed = True
        if energy_now() > ENERGY_MAX and _pct("Fat") > 12.2 and _pct("Protein") > 32.2:
            for it in rows_meat_b():
                if energy_now() <= ENERGY_MAX: break
                if it["dm_g"] > 0 and shrink_item_dm(it, 10.0):
                    renorm_dm()
                    if _pct("Fat") < 12.0 or _pct("Protein") < 32.0:
                        grow_item_dm(it, 10.0); renorm_dm()
                    else:
                        issues.append("Energy > 4500 → reduced Group B meat by 10 g.")
                        changed = True
        if energy_now() > ENERGY_MAX and _pct("CHO") > 25.2:
            gr = rows_grains(); gr.sort(key=energy_density, reverse=True)
            for it in gr:
                if energy_now() <= ENERGY_MAX: break
                if it["dm_g"] <= 0: continue
                if shrink_item_dm(it, 10.0):
                    renorm_dm()
                    if _pct("CHO") < 25.0:
                        grow_item_dm(it, 10.0); renorm_dm()
                    else:
                        issues.append(f"Energy > 4500 → reduced grain ({it['ingredient']}) by 10 g.")
                        changed = True
        safety += 1
        if not changed:
            issues.append("Energy > 4500 but further trims would break macro limits.")
            break

    # --- FINAL settles to avoid ping-pong ---
    def final_fiber_settle():
        HARD_FIBER_MAX = 6.0
        veg_names_local = {r["ingredient_name"].strip().lower() for r in (veg_a + veg_b + veg_c)}
        def is_veg_local(it): return it["ingredient"].strip().lower() in veg_names_local

        loops = 0
        while (totals["Fiber"] * 100.0 / FIXED_TOTAL_DM) > HARD_FIBER_MAX and loops < 30:
            rows = [x for x in ingredient_totals if is_veg_local(x) and x["dm_g"] > 0]
            if not rows:
                break
            rows.sort(key=lambda it: (it["fiber_g"] / max(it["dm_g"], 1e-9)), reverse=True)
            cut = min(5.0, rows[0]["dm_g"])
            if shrink_item_dm(rows[0], cut):
                issues.append(f"Final fiber trim → reduced {rows[0]['ingredient']} by {int(cut)} g.")
                _refresh_totals()
                dm_now2 = round(sum(x["dm_g"] for x in ingredient_totals), 2)
                dm_gap2 = round(FIXED_TOTAL_DM - dm_now2, 2)
                if abs(dm_gap2) >= 0.5:
                    topup_or_trim_without_fiber(dm_gap2)
            loops += 1

    def final_fat_settle():
        FAT_MIN_LOC, FAT_MAX_LOC = 12.0, 17.0
        def fat_pct_now(): return totals["Fat"] * 100.0 / FIXED_TOTAL_DM
        oil_set = {r["ingredient_name"].strip().lower() for r in oils}
        b_set   = meats_b_set
        c_set   = meats_c_set

        safety = 0
        while safety < 20:
            f = fat_pct_now()
            changed = False
            if f > FAT_MAX_LOC + 0.15:
                for it in [x for x in ingredient_totals if x["ingredient"].strip().lower() in oil_set]:
                    if f <= FAT_MAX_LOC + 0.15: break
                    if it["dm_g"] > 0 and shrink_item_dm(it, 5.0):
                        issues.append("Final fat trim → reduced oil by 5 g.")
                        _refresh_totals(); f = fat_pct_now(); changed = True
                for S, label in ((b_set, "Group B meat"), (c_set, "Group C meat")):
                    if f <= FAT_MAX_LOC + 0.15: break
                    for it in [x for x in ingredient_totals if x["ingredient"].strip().lower() in S]:
                        if f <= FAT_MAX_LOC + 0.15: break
                        if it["dm_g"] > 0 and shrink_item_dm(it, 10.0):
                            issues.append(f"Final fat trim → reduced {label} by 10 g.")
                            _refresh_totals(); f = fat_pct_now(); changed = True
            elif f < FAT_MIN_LOC - 0.15:
                co = next((x for x in ingredient_totals if x["ingredient"].strip().lower() == "coconut oil"), None)
                if co and grow_item_dm(co, 5.0):
                    issues.append("Final fat raise → added 5 g coconut oil.")
                    _refresh_totals(); changed = True
                else:
                    it = next((x for x in ingredient_totals if x["ingredient"].strip().lower() in b_set), None)
                    if it and grow_item_dm(it, 5.0):
                        _refresh_totals()
                        if (totals["Protein"] * 100.0 / FIXED_TOTAL_DM) > 42.0:
                            shrink_item_dm(it, 5.0); _refresh_totals()
                        else:
                            issues.append("Final fat raise → increased Group B meat by 5 g.")
                            changed = True

            dm_now2 = round(sum(x["dm_g"] for x in ingredient_totals), 2)
            dm_gap2 = round(FIXED_TOTAL_DM - dm_now2, 2)
            if abs(dm_gap2) >= 0.5:
                topup_or_trim_without_fiber(dm_gap2)
                grain_guard()
                organ_guard()

            if not changed:
                break
            safety += 1

    final_fiber_settle()
    final_fat_settle()

    # --- FINAL PROTEIN settle (32–42%) ---
    def final_protein_settle():
        PRO_MIN_LOC, PRO_MAX_LOC = 32.0, 42.0
        safety = 0
        while safety < 40:
            p = table_pct("Protein")
            changed = False
            if p > PRO_MAX_LOC + 0.2:
                for it in [x for x in ingredient_totals if x["ingredient"].strip().lower() in meats_a_set]:
                    if p <= PRO_MAX_LOC + 0.2: break
                    if it["dm_g"] > 0 and shrink_item_dm(it, 10.0):
                        issues.append("Protein > 42% → reduced Group A meat by 10 g.")
                        _refresh_totals(); p = table_pct("Protein"); changed = True
                if p > PRO_MAX_LOC + 0.2:
                    for it in [x for x in ingredient_totals if x["ingredient"].strip().lower() in meats_b_set]:
                        if p <= PRO_MAX_LOC + 0.2: break
                        if it["dm_g"] > 0 and shrink_item_dm(it, 10.0):
                            issues.append("Protein > 42% → reduced Group B meat by 10 g.")
                            _refresh_totals(); p = table_pct("Protein"); changed = True
                if p > PRO_MAX_LOC + 0.2:
                    for it in [x for x in ingredient_totals if it["ingredient"].strip().lower() in liver_names]:
                        if p <= PRO_MAX_LOC + 0.2: break
                        cut = min(10.0, max(0.0, it["dm_g"] - 120.0))
                        if cut >= 1e-9 and shrink_item_dm(it, cut):
                            issues.append(f"Protein > 42% → reduced liver by {cut:.0f} g.")
                            _refresh_totals(); p = table_pct("Protein"); changed = True
            elif p < PRO_MIN_LOC - 0.2:
                for s, label in ((meats_a_set, "Group A meat"), (meats_c_set, "Group C meat")):
                    for it in [x for x in ingredient_totals if x["ingredient"].strip().lower() in s]:
                        if p >= PRO_MIN_LOC - 0.2: break
                        if grow_item_dm(it, 10.0):
                            issues.append(f"Protein < 32% → increased {label} by 10 g.")
                            _refresh_totals(); p = table_pct("Protein"); changed = True
                    if p >= PRO_MIN_LOC - 0.2: break
                if p < PRO_MIN_LOC - 0.2:
                    for is_pred, label in ((is_grain, "grain"), (is_veg_c, "veg C")):
                        for it in [x for x in ingredient_totals if is_pred(it)]:
                            if p >= PRO_MIN_LOC - 0.2: break
                            if it["dm_g"] > 0 and shrink_item_dm(it, 10.0):
                                issues.append(f"Protein < 32% → reduced {label} by 10 g to raise concentration.")
                                _refresh_totals(); p = table_pct("Protein"); changed = True
                        if p >= PRO_MIN_LOC - 0.2: break

            dm_now3 = round(sum(x["dm_g"] for x in ingredient_totals), 2)
            dm_gap3 = round(FIXED_TOTAL_DM - dm_now3, 2)
            if abs(dm_gap3) >= 0.5:
                topup_or_trim_without_fiber(dm_gap3)
                grain_guard()

            if not changed:
                break
            safety += 1

    final_protein_settle()

    # ---- FINAL: keep all user-selected items non-zero & hide 0-g rows ----
    def _is_selected_row(it):
        return (
            it["ingredient"].strip().lower() in {r["ingredient_name"].strip().lower() for r in picks}
            and not it.get("fixed", False)
        )

    # 1) bump any selected item that ended up at 0 g back to at least 5 g
    bumped = 0.0
    for it in [x for x in ingredient_totals if _is_selected_row(x) and x["dm_g"] <= 0.0]:
        if grow_item_dm(it, 5.0):
            bumped += 5.0

    # free the same grams from grains while keeping the 300 g floor
    if bumped > 0:
        def _cut_some(rows, left):
            rows.sort(key=lambda r: r["dm_g"], reverse=True)
            for r in rows:
                if left <= 0:
                    break
                spare = max(0.0, grains_dm_total() - 300.0)
                if spare <= 0:
                    break
                cut = min(5.0, r["dm_g"], left, spare)
                if cut > 0 and shrink_item_dm(r, cut):
                    left = round(left - cut, 2)
            return left

        gA_rows = [x for x in ingredient_totals if x["ingredient"].strip().lower() in grains_a_set]
        gB_rows = [x for x in ingredient_totals if x["ingredient"].strip().lower() in grains_b_set]

        left = round(bumped, 2)
        left = _cut_some(gA_rows, left)
        if left > 0:
            _cut_some(gB_rows, left)

        # re-check grains/organs/meat constraints and DM=1000
        grain_guard_strict()
        organ_guard()
        enforce_meat_rules()

        dm_now2 = round(sum(x["dm_g"] for x in ingredient_totals), 2)
        dm_gap2 = round(FIXED_TOTAL_DM - dm_now2, 2)
        if abs(dm_gap2) >= 0.5:
            topup_or_trim_without_fiber(dm_gap2)

    # 2) drop any 0-g rows from the final table (including fixed items with 0)
    ingredient_totals = [it for it in ingredient_totals if round(it["dm_g"], 2) > 0.0]

    # 3) recompute totals from the filtered table
    new_totals = recalc_totals_from_table(ingredient_totals)
    for k in totals:
        totals[k] = new_totals[k]

    # ---------- recompute result (post-tuning) ----------
    result = {
        "Protein_percent": round(totals["Protein"] * 100.0 / FIXED_TOTAL_DM, 2),
        "Fat_percent": round(totals["Fat"] * 100.0 / FIXED_TOTAL_DM, 2),
        "CHO_percent": round(totals["CHO"] * 100.0 / FIXED_TOTAL_DM, 2),
        "Fiber_percent": round(totals["Fiber"] * 100.0 / FIXED_TOTAL_DM, 2),
        "Ash_percent": round(totals["Ash"] * 100.0 / FIXED_TOTAL_DM, 2),
        "Ca_percent": round(totals["Ca"] * 100.0 / FIXED_TOTAL_DM, 2),
        "P_percent": round(totals["P"] * 100.0 / FIXED_TOTAL_DM, 2),
        "Ca_P_ratio": round(totals["Ca"] / totals["P"], 2) if totals["P"] else 0.0,
        "Energy": round(totals["Energy"], 2),
        "DM_percent": FIXED_TOTAL_DM,
    }

    # Build breakdown from the FINAL table so it matches UI exactly
    final_breakdown = [
        {
            "ingredient": it["ingredient"],
            "dm_g": round(float(it["dm_g"]), 2),
            "fixed": bool(it.get("fixed", False)),
        }
        for it in ingredient_totals
    ]
    final_breakdown.sort(key=lambda r: (not r["fixed"], r["ingredient"].lower()))

    return {
        "nutrient_percentages": result,
        "dm_breakdown": final_breakdown,
        "ingredient_totals": ingredient_totals,
        "issues": issues,
        "auto_added": None,
    }