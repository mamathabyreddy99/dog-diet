# backend/services/diet_service.py
from pathlib import Path
from typing import List, Dict, Any, Optional
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
    totals["Iron"]    += float(row["iron_mg"])       * dm / 100.0  # mg
    totals["Energy"]  += float(row["energy_kcal"])   * dm / 100.0

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

# ---------- robust normalizers ----------
def gname(s: pd.Series) -> str:
    # normalize group_name: lowercase + collapse spaces
    raw = str(s.get("group_name", "")).lower()
    return " ".join(raw.split())

def _normkey(x: str) -> str:
    # normalize ingredient names for matching
    return " ".join(
        str(x).lower()
        .replace("–", "-").replace("—", "-")
        .replace("’", "'").replace("`", "'")
        .split()
    )

# ============================================================================
# Deterministic allocator + auto-balance controller
def calculate_diet(selected_names: List[str]) -> Dict[str, Any]:
    """
    NEW VEGETABLE RULES:
      * Veg A only: 80 g total
      * Veg B only: 70 g total
      * Both A+B: 30 g A + 70 g B (total 100 g)
      * Veg C (potato): optional up to 100 g (used by the macro-balancer as a low-fibre CHO)
    """
    # Load data
    fdf = fixed_df()
    udf = user_df()

    dm_breakdown_raw: List[Dict[str, Any]] = []
    ingredient_totals: List[Dict[str, Any]] = []
    totals = {k: 0.0 for k in ["Protein", "Fat", "CHO", "Fiber", "Ash", "Ca", "P", "Iron", "Energy"]}
    issues: List[str] = []

    # ---------- Fixed items ----------
    fixed_dm_used = 0.0
    for _, r in fdf.iterrows():
        dm = float(r["dm_g"])
        if dm <= 0:
            continue
        _add_row(totals, dm, r)
        dm_breakdown_raw.append({"ingredient": r["ingredient_name"], "dm_g": round(dm, 2), "fixed": True})
        ingredient_totals.append({
            "ingredient": r["ingredient_name"],
            "dm_g": round(dm, 2),
            "protein_g": round(float(r["protein_g"]) * dm / 100.0, 2),
            "fat_g": round(float(r["fat_g"]) * dm / 100.0, 2),
            "cho_g": round(float(r["cho_g"]) * dm / 100.0, 2),
            "fiber_g": round(float(r["fiber_g"]) * dm / 100.0, 2),
            "ash_g": round(float(r["ash_g"]) * dm / 100.0, 2),
            "ca_mg": round(float(r["calcium_mg"]) * dm / 100.0, 2),
            "p_mg": round(float(r["phosphorus_mg"]) * dm / 100.0, 2),
            "iron_mg": round(float(r["iron_mg"]) * dm / 100.0, 2),
            "energy_kcal": round(float(r["energy_kcal"]) * dm / 100.0, 2),
            "fixed": True,
        })
        fixed_dm_used += dm

    remaining = max(0.0, FIXED_TOTAL_DM - fixed_dm_used)

    # ---------- User selections (unique, robust) ----------
    seen: set = set()
    picks: List[pd.Series] = []
    for name in selected_names:
        key = _normkey(name)
        if key in seen:
            continue
        seen.add(key)
        found = udf[udf["ingredient_name"].apply(_normkey) == key]
        if not found.empty:
            picks.append(found.iloc[0])

    # ---------- Partition by exact group (after normalization) ----------
    meats_a = [r for r in picks if gname(r) == "meat group a"]
    meats_b = [r for r in picks if gname(r) == "meat group b"]
    meats_c = [r for r in picks if gname(r) == "meat group c"]
    grains_a = [r for r in picks if gname(r) == "grain a"]
    grains_b = [r for r in picks if gname(r) == "grain b"]
    veg_a    = [r for r in picks if gname(r) == "vegetable a"]
    veg_b    = [r for r in picks if gname(r) == "vegetable b"]
    veg_c    = [r for r in picks if gname(r) == "vegetable c"]
    oils     = [r for r in picks if gname(r) == "oil"]
    fruits   = [r for r in picks if gname(r) == "fruit"]
    organs   = [r for r in picks if gname(r) == "organ" and "liver" not in str(r["ingredient_name"]).lower()]
    livers   = [r for r in picks if "liver" in str(r["ingredient_name"]).lower()]

    # ---------- Local add helper ----------
    def _add_item(row: pd.Series, dm: float):
        nonlocal remaining
        if dm <= 0 or remaining <= 0:
            return 0.0
        dm = min(dm, remaining)
        name = row["ingredient_name"]

        _add_row(totals, dm, row)
        dm_breakdown_raw.append({"ingredient": name, "dm_g": round(dm, 2), "fixed": False})

        # merge if already exists (user item)
        for item in ingredient_totals:
            if item.get("ingredient") == name and not item.get("fixed", False):
                item["dm_g"]        = round(item["dm_g"] + dm, 2)
                item["protein_g"]   = round(item["protein_g"]   + float(row["protein_g"])   * dm / 100.0, 2)
                item["fat_g"]       = round(item["fat_g"]       + float(row["fat_g"])       * dm / 100.0, 2)
                item["cho_g"]       = round(item["cho_g"]       + float(row["cho_g"])       * dm / 100.0, 2)
                item["fiber_g"]     = round(item["fiber_g"]     + float(row["fiber_g"])     * dm / 100.0, 2)
                item["ash_g"]       = round(item["ash_g"]       + float(row["ash_g"])       * dm / 100.0, 2)
                item["ca_mg"]       = round(item["ca_mg"]       + float(row["calcium_mg"])  * dm / 100.0, 2)
                item["p_mg"]        = round(item["p_mg"]        + float(row["phosphorus_mg"]) * dm / 100.0, 2)
                item["iron_mg"]     = round(item["iron_mg"]     + float(row["iron_mg"])     * dm / 100.0, 2)
                item["energy_kcal"] = round(item["energy_kcal"] + float(row["energy_kcal"]) * dm / 100.0, 2)
                remaining -= dm
                return dm

        ingredient_totals.append({
            "ingredient": name,
            "dm_g": round(dm, 2),
            "protein_g":   round(float(row["protein_g"])   * dm / 100.0, 2),
            "fat_g":       round(float(row["fat_g"])       * dm / 100.0, 2),
            "cho_g":       round(float(row["cho_g"])       * dm / 100.0, 2),
            "fiber_g":     round(float(row["fiber_g"])     * dm / 100.0, 2),
            "ash_g":       round(float(row["ash_g"])       * dm / 100.0, 2),
            "ca_mg":       round(float(row["calcium_mg"])  * dm / 100.0, 2),
            "p_mg":        round(float(row["phosphorus_mg"]) * dm / 100.0, 2),
            "iron_mg":     round(float(row["iron_mg"])       * dm / 100.0, 2),
            "energy_kcal": round(float(row["energy_kcal"])   * dm / 100.0, 2),
            "fixed": False,
        })
        remaining -= dm
        return dm

    # ---------- Allocation constants (g) ----------
    LIVER_DM      = 100.0
    OTHER_ORG_DM  = 50.0
    OILS_DM       = 10.0

    # NEW VEGETABLE RULES
    VEG_A_ONLY_DM = 80.0      # A only
    VEG_B_ONLY_DM = 70.0      # B only
    VEG_AB_A_DM   = 30.0      # when both selected
    VEG_AB_B_DM   = 70.0
    POTATO_MAX_DM = 100.0

    # Grains & meat
    GRAIN_B_DM    = 150.0
    GRAIN_MIN     = 300.0
    GRAIN_MAX     = 400.0
    MEAT_TARGET   = 280.0
    MEAT_MIN      = 200.0
    MEAT_MAX      = 350.0
    FRUIT_MAX_DM  = 25.0
    GRAIN_A_ITEM_CAP = 150.0

    # ---------- 1) Organs ----------
    if livers:
        _add_item(livers[0], LIVER_DM)
    else:
        issues.append("Liver is mandatory (≥100 g) but not selected.")

    if organs:
        per = OTHER_ORG_DM / len(organs)
        for i, r in enumerate(organs):
            dm = per if i < len(organs) - 1 else OTHER_ORG_DM - per * (len(organs) - 1)
            _add_item(r, dm)
    elif OTHER_ORG_DM > 0:
        issues.append("No non-liver organ selected; cannot allocate 50 g of other organs.")

    # ---------- 2) Oils ----------
    if oils:
        per = OILS_DM / len(oils)
        for i, r in enumerate(oils):
            dm = per if i < len(oils) - 1 else OILS_DM - per * (len(oils) - 1)
            _add_item(r, dm)
    elif OILS_DM > 0:
        issues.append("No oil selected; cannot allocate 10 g total oils.")

    # ---------- 3) NEW VEGETABLE ALLOCATION ----------
    vegA_selected = bool(veg_a)
    vegB_selected = bool(veg_b)

    if vegA_selected and vegB_selected:
        # Both A and B selected → A=30 g, B=70 g (total 100 g)
        per_a = VEG_AB_A_DM / len(veg_a)
        for i, r in enumerate(veg_a):
            dm = per_a if i < len(veg_a) - 1 else VEG_AB_A_DM - per_a * (len(veg_a) - 1)
            _add_item(r, dm)

        per_b = VEG_AB_B_DM / len(veg_b)
        for i, r in enumerate(veg_b):
            dm = per_b if i < len(veg_b) - 1 else VEG_AB_B_DM - per_b * (len(veg_b) - 1)
            _add_item(r, dm)

    elif vegA_selected:
        # Only A selected → 80 g total
        per_a = VEG_A_ONLY_DM / len(veg_a)
        for i, r in enumerate(veg_a):
            dm = per_a if i < len(veg_a) - 1 else VEG_A_ONLY_DM - per_a * (len(veg_a) - 1)
            _add_item(r, dm)

    elif vegB_selected:
        # Only B selected → 70 g total
        per_b = VEG_B_ONLY_DM / len(veg_b)
        for i, r in enumerate(veg_b):
            dm = per_b if i < len(veg_b) - 1 else VEG_B_ONLY_DM - per_b * (len(veg_b) - 1)
            _add_item(r, dm)

    # ---------- 4) Grains ----------
    if grains_b:
        per = GRAIN_B_DM / len(grains_b)
        for i, r in enumerate(grains_b):
            dm = per if i < len(grains_b) - 1 else GRAIN_B_DM - per * (len(grains_b) - 1)
            _add_item(r, dm)
    else:
        issues.append("No Grain B selected; cannot allocate 150 g of Grain B.")

    grains_b_used = sum(
        it["dm_g"] for it in ingredient_totals
        if it["ingredient"] in [r["ingredient_name"] for r in grains_b]
    )
    grain_a_target_min = max(0.0, GRAIN_MIN - grains_b_used)
    grain_a_target_max = max(0.0, GRAIN_MAX - grains_b_used)

    if grains_a:
        grain_a_dm = min(grain_a_target_max, remaining)
        if grain_a_dm < grain_a_target_min and remaining >= grain_a_target_min:
            grain_a_dm = grain_a_target_min
        per = grain_a_dm / len(grains_a) if grains_a else 0.0
        for i, r in enumerate(grains_a):
            dm = per if i < len(grains_a) - 1 else round(grain_a_dm - per * (len(grains_a) - 1), 2)
            _add_item(r, dm)
    elif grain_a_target_min > 0:
        issues.append("No Grain A selected; cannot meet minimum total grain DM of 300 g.")

    # ---------- 5) Meat ----------
    meat_dm_available = remaining
    meat_target_dm = max(MEAT_MIN, min(MEAT_MAX, MEAT_TARGET, meat_dm_available))
    meats_selected = []
    if meats_a:
        meats_selected.append(meats_a[0])
    if meats_b:
        meats_selected.append(meats_b[0])
    if not meats_selected and meats_c:
        meats_selected.append(meats_c[0])
    if not meats_selected and meat_target_dm > 0:
        issues.append("No meat selected; cannot allocate meat DM.")
    if meats_selected and meat_target_dm > 0:
        per = meat_target_dm / len(meats_selected)
        for i, r in enumerate(meats_selected):
            dm = per if i < len(meats_selected) - 1 else meat_target_dm - per * (len(meats_selected) - 1)
            _add_item(r, dm)

    # ---------- 6) Fruits (reserve up to 25 g; free room if needed) ----------
    def _sum_dm(names: set) -> float:
        return round(sum(it["dm_g"] for it in ingredient_totals if it["ingredient"] in names), 2)

    if fruits:
        fruit_target = FRUIT_MAX_DM
        fruit_dm = min(fruit_target, remaining)

        grain_a_names = {r["ingredient_name"] for r in grains_a}
        grain_b_names = {r["ingredient_name"] for r in grains_b}
        meatA_names   = {r["ingredient_name"] for r in meats_a}
        meat_names    = {r["ingredient_name"] for r in meats_a + meats_b + meats_c}

        # try to free from Grain A above its floor
        if fruit_dm < fruit_target and grain_a_names:
            grain_a_rows = [it for it in ingredient_totals if it["ingredient"] in grain_a_names]
            ga_total = _sum_dm(grain_a_names)
            gb_total = _sum_dm(grain_b_names)
            ga_floor = max(0.0, GRAIN_MIN - gb_total)
            available = max(0.0, ga_total - ga_floor)
            need = min(fruit_target - fruit_dm, available)
            if need > 0:
                adjust = 0.0
                for i, it in enumerate(grain_a_rows):
                    share = it["dm_g"] / ga_total if ga_total else 0.0
                    change = round(need * share, 2)
                    if i == len(grain_a_rows) - 1:
                        change = round(need - adjust, 2)
                    cut = min(change, it["dm_g"])
                    base = it["dm_g"]
                    scale = (base - cut) / base if base else 1.0
                    for k in ["protein_g","fat_g","cho_g","fiber_g","ash_g","ca_mg","p_mg","iron_mg","energy_kcal"]:
                        it[k] = round(it[k] * scale, 2)
                    it["dm_g"] = round(base - cut, 2)
                    adjust += cut
                remaining += need
                fruit_dm += need

        # free from meats while keeping floors (A≥150, total≥200)
        if fruit_dm < fruit_target and meat_names:
            need = fruit_target - fruit_dm
            step = 5.0
            attempts = 0
            while need > 1e-9 and attempts < 200:
                attempts += 1
                meat_total_now = _sum_dm(meat_names)
                meatA_total_now = _sum_dm(meatA_names)
                candidate = None
                for it in ingredient_totals:
                    nm = it["ingredient"]
                    if nm not in meat_names or it["dm_g"] < step:
                        continue
                    if nm in meatA_names:
                        if (meatA_total_now - step) < 150.0:
                            continue
                    if (meat_total_now - step) < 200.0:
                        continue
                    candidate = it
                    break
                if candidate is None:
                    break
                base = candidate["dm_g"]
                scale = (base - step) / base
                for k in ["protein_g","fat_g","cho_g","fiber_g","ash_g","ca_mg","p_mg","iron_mg","energy_kcal"]:
                    candidate[k] = round(candidate[k] * scale, 2)
                candidate["dm_g"] = round(base - step, 2)
                remaining += step
                fruit_dm += step
                need = max(0.0, fruit_target - fruit_dm)

        if fruit_dm > 0:
            per = fruit_dm / len(fruits)
            allocated = 0.0
            for i, r in enumerate(fruits):
                dm = round(per if i < len(fruits) - 1 else fruit_dm - allocated, 2)
                allocated += dm
                _add_item(r, dm)

    # ---------- proportional DM adjust helpers ----------
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

    def adjust_pool(pool: List[Dict[str, Any]], delta: float):
        """Adjust DM across pool by delta (+ adds, - removes) proportionally."""
        if not pool or delta == 0:
            return 0.0
        total_pool_dm = sum(x["dm_g"] for x in pool)
        if total_pool_dm <= 0:
            return 0.0
        adjusted = 0.0
        for i, it in enumerate(pool):
            share = it["dm_g"] / total_pool_dm
            change = round(delta * share, 2)
            if i == len(pool) - 1:
                change = round(delta - adjusted, 2)
            if delta > 0:
                grow_item_dm(it, change)
            else:
                cut = min(-change, it["dm_g"])
                shrink_item_dm(it, cut)
                change = -cut
            adjusted += change
        return adjusted

    # ---------- Normalize to exactly 1000 g ----------
    dm_now = round(sum(x["dm_g"] for x in ingredient_totals), 2)
    dm_gap = round(FIXED_TOTAL_DM - dm_now, 2)
    if abs(dm_gap) >= 0.5:
        grain_a_rows = [x for x in ingredient_totals if x["ingredient"] in [r["ingredient_name"] for r in grains_a]]
        meat_rows    = [x for x in ingredient_totals if x["ingredient"] in [r["ingredient_name"] for r in meats_a + meats_b + meats_c]]
        if dm_gap > 0:
            adjusted = adjust_pool(grain_a_rows, dm_gap)
            if abs(dm_gap - adjusted) > 0.01:
                adjust_pool(meat_rows, dm_gap - adjusted)
        else:
            adjusted = adjust_pool(grain_a_rows, dm_gap)
            if abs(dm_gap - adjusted) > 0.01:
                adjust_pool(meat_rows, dm_gap - adjusted)

    # ---------- Enforce meat minimums by shifting from Grain A ----------
    def recompute_totals_from_sources() -> Dict[str, float]:
        new = {k: 0.0 for k in totals}
        for item in ingredient_totals:
            name = item["ingredient"]
            dm_val = item["dm_g"]
            src = None
            sr = udf[udf["ingredient_name"].str.lower() == name.strip().lower()]
            if not sr.empty:
                src = sr.iloc[0]
            else:
                sr = fdf[fdf["ingredient_name"].str.lower() == name.strip().lower()]
                if not sr.empty:
                    src = sr.iloc[0]
            if src is not None:
                new["Protein"] += float(src["protein_g"]) * dm_val / 100.0
                new["Fat"]     += float(src["fat_g"])     * dm_val / 100.0
                new["CHO"]     += float(src["cho_g"])     * dm_val / 100.0
                new["Fiber"]   += float(src["fiber_g"])   * dm_val / 100.0
                new["Ash"]     += float(src["ash_g"])     * dm_val / 100.0
                new["Ca"]      += float(src["calcium_mg"])    * dm_val / 100.0 / 1000.0
                new["P"]       += float(src["phosphorus_mg"]) * dm_val / 100.0 / 1000.0
                new["Iron"]    += float(src["iron_mg"])       * dm_val / 100.0
                new["Energy"]  += float(src["energy_kcal"])   * dm_val / 100.0
        return new

    meat_a_names = {r["ingredient_name"] for r in meats_a}
    meat_b_names = {r["ingredient_name"] for r in meats_b}
    meat_c_names = {r["ingredient_name"] for r in meats_c}

    def sum_dm(names: set) -> float:
        return sum(it["dm_g"] for it in ingredient_totals if it["ingredient"] in names)

    meat_a_dm_now = sum_dm(meat_a_names)
    meat_b_dm_now = sum_dm(meat_b_names)
    meat_c_dm_now = sum_dm(meat_c_names)
    meat_total_dm = meat_a_dm_now + meat_b_dm_now + meat_c_dm_now

    groups_selected = (1 if meat_a_dm_now > 0 else 0) + (1 if meat_b_dm_now > 0 else 0) + (1 if meat_c_dm_now > 0 else 0)

    primary_group = None
    if meats_a:
        primary_group = meats_a[0]["ingredient_name"]
        primary_dm_now = meat_a_dm_now
    elif meats_b:
        primary_group = meats_b[0]["ingredient_name"]
        primary_dm_now = meat_b_dm_now
    elif meats_c:
        primary_group = meats_c[0]["ingredient_name"]
        primary_dm_now = meat_c_dm_now
    else:
        primary_dm_now = 0.0

    needed_primary = 0.0
    if primary_group and groups_selected > 1:
        needed_primary = 150.0 - primary_dm_now
    needed_total = 200.0 - meat_total_dm
    needed = max(0.0, needed_primary, needed_total)

    if primary_group and needed > 0:
        grain_a_names = {r["ingredient_name"] for r in grains_a}
        grain_b_names = {r["ingredient_name"] for r in grains_b}
        grain_a_dm_now = sum_dm(grain_a_names)
        grain_b_dm_now = sum_dm(grain_b_names)
        grain_a_floor = max(0.0, GRAIN_MIN - grain_b_dm_now)
        available = max(0.0, grain_a_dm_now - grain_a_floor)
        allowed_increase = MEAT_MAX - meat_total_dm
        transfer = min(needed, available, allowed_increase)

        if transfer > 0:
            grain_a_rows = [it for it in ingredient_totals if it["ingredient"] in grain_a_names]
            adjust_pool(grain_a_rows, -transfer)
            for it in ingredient_totals:
                if it["ingredient"] == primary_group:
                    grow_item_dm(it, transfer)
                    break
            totals = recompute_totals_from_sources()
            issues.append(f"Raised meat to meet minimums by shifting {transfer:.0f} g from Grain A to {primary_group}.")
        else:
            issues.append("Could not meet meat minimums without breaking grain or meat limits.")

    # ---------- Macro helpers ----------
    def compute_totals():
        return recompute_totals_from_sources()

    def compute_macros():
        t = compute_totals()
        return t, {
            "Protein_pct": t["Protein"] * 100.0 / FIXED_TOTAL_DM,
            "Fat_pct":     t["Fat"]     * 100.0 / FIXED_TOTAL_DM,
            "Fiber_pct":   t["Fiber"]   * 100.0 / FIXED_TOTAL_DM,
            "CHO_pct":     t["CHO"]     * 100.0 / FIXED_TOTAL_DM,
            "Energy":      t["Energy"],
        }

    meat_names_set = {r["ingredient_name"] for r in meats_a + meats_b + meats_c}
    grain_a_names  = {r["ingredient_name"] for r in grains_a}
    grain_b_names  = {r["ingredient_name"] for r in grains_b}
    oil_names_set  = {r["ingredient_name"] for r in oils}
    vegA_names     = {r["ingredient_name"] for r in veg_a}
    vegB_names     = {r["ingredient_name"] for r in veg_b}
    vegC_names     = {r["ingredient_name"] for r in veg_c}

    grain_min_value = 300.0  # capture once

    def safe_transfer(donor, receiver, delta) -> bool:
        """Guarded 5 g transfer respecting floors/caps (incl. NEW veg floors)."""
        if donor is None or receiver is None or delta <= 0:
            return False
        if donor.get("fixed", False) or donor["dm_g"] < delta:
            return False

        name_d = donor["ingredient"]
        name_r = receiver["ingredient"]

        def group_sum(names: set) -> float:
            return sum(it["dm_g"] for it in ingredient_totals if it["ingredient"] in names)

        grain_a_total = group_sum(grain_a_names)
        grain_b_total = group_sum(grain_b_names)
        grain_a_floor = max(0.0, grain_min_value - grain_b_total)

        meat_total = group_sum(meat_names_set)
        meatA_names = {r["ingredient_name"] for r in meats_a}
        meatA_total = group_sum(meatA_names)

        vegA_total = group_sum(vegA_names)
        vegB_total = group_sum(vegB_names)

        # NEW vegetable floors based on selected sets
        vegA_floor = 0.0
        vegB_floor = 0.0
        if vegA_names and vegB_names:
            vegA_floor, vegB_floor = 30.0, 70.0
        elif vegA_names:
            vegA_floor = 80.0
        elif vegB_names:
            vegB_floor = 70.0

        if name_d in vegA_names and (vegA_total - delta) < vegA_floor:
            return False
        if name_d in vegB_names and (vegB_total - delta) < vegB_floor:
            return False

        if name_d in grain_b_names:
            return False
        if name_d in grain_a_names and (grain_a_total - delta) < grain_a_floor:
            return False
        if name_d in meat_names_set:
            if (meat_total - delta) < 200.0:
                return False
            if name_d in meatA_names and (meatA_total - delta) < 150.0:
                return False

        # caps
        if name_r in meat_names_set and (meat_total + delta) > MEAT_MAX:
            return False
        if name_r in grain_a_names and (receiver["dm_g"] + delta) > GRAIN_A_ITEM_CAP:
            return False
        if name_r in grain_b_names:
            return False

        if not shrink_item_dm(donor, delta):
            return False
        if not grow_item_dm(receiver, delta):
            grow_item_dm(donor, delta)
            return False
        return True

    # ---------- Macro adjustment (5 g guarded transfers) ----------
    max_adjustments = 40
    for _ in range(max_adjustments):
        totals_cur, macros = compute_macros()
        prot_pct = macros["Protein_pct"]
        fat_pct  = macros["Fat_pct"]
        fib_pct  = macros["Fiber_pct"]
        cho_pct  = macros["CHO_pct"]
        energy_val = macros["Energy"]

        if (32.0 <= prot_pct <= 40.0 and
            12.0 <= fat_pct  <= 17.0 and
             3.0 <= fib_pct  <=  6.0 and
            30.0 <= cho_pct  <= 45.0 and
            4000.0 <= energy_val <= 4500.0):
            totals = totals_cur
            break

        adjusted = False

        # High fat/energy → trim oils or high-fat meats into grains/lean meats
        if (fat_pct > 17.0 or energy_val > 4500.0) and not adjusted:
            donors = [(it, (it["fat_g"] / it["dm_g"]) if it["dm_g"] else 0.0)
                      for it in ingredient_totals
                      if not it.get("fixed", False) and it["dm_g"] >= 5.0 and
                         (it["ingredient"] in oil_names_set or it["ingredient"] in meat_names_set)]
            receivers = [(it, (it["fat_g"] / it["dm_g"]) if it["dm_g"] else 0.0)
                         for it in ingredient_totals
                         if (it["ingredient"] in grain_a_names) or (it["ingredient"] in meat_names_set)]
            donors.sort(key=lambda x: x[1], reverse=True)
            receivers.sort(key=lambda x: x[1])
            for d, _ in donors:
                for r, _ in receivers:
                    if r["ingredient"] in oil_names_set:
                        continue
                    if safe_transfer(d, r, 5.0):
                        adjusted = True
                        break
                if adjusted:
                    break
            if adjusted:
                continue

        # Low protein or high CHO → move from high-CHO Grain A to high-protein meat
        if (prot_pct < 32.0 or cho_pct > 45.0) and not adjusted:
            donors = [(it, (it["cho_g"] / it["dm_g"]) if it["dm_g"] else 0.0)
                      for it in ingredient_totals
                      if it["ingredient"] in grain_a_names and it["dm_g"] >= 5.0]
            receivers = [(it, (it["protein_g"] / it["dm_g"]) if it["dm_g"] else 0.0)
                         for it in ingredient_totals
                         if it["ingredient"] in meat_names_set]
            donors.sort(key=lambda x: x[1], reverse=True)
            receivers.sort(key=lambda x: x[1], reverse=True)
            for d, _ in donors:
                for r, _ in receivers:
                    if safe_transfer(d, r, 5.0):
                        adjusted = True
                        break
                if adjusted:
                    break
            if adjusted:
                continue

        # Protein high OR CHO low → move from leanest meat to lowest-fibre CHO (potato first)
        if ((prot_pct > 40.0 or cho_pct < 30.0) and not adjusted):
            donors = [(it, (it["protein_g"] / it["dm_g"]) if it["dm_g"] else 0.0)
                      for it in ingredient_totals
                      if it["ingredient"] in meat_names_set and it["dm_g"] >= 5.0]
            donors.sort(key=lambda x: x[1], reverse=True)

            receivers: list[tuple[dict, float]] = []
            for it in ingredient_totals:
                if it["ingredient"] in vegC_names and (it["dm_g"] + 5.0) <= POTATO_MAX_DM:
                    dens = (it["fiber_g"] / it["dm_g"]) if it["dm_g"] else 0.0
                    receivers.append((it, dens))
            for it in ingredient_totals:
                if it["ingredient"] in grain_a_names and (it["dm_g"] + 5.0) <= GRAIN_A_ITEM_CAP:
                    dens = (it["fiber_g"] / it["dm_g"]) if it["dm_g"] else 0.0
                    receivers.append((it, dens))
            receivers.sort(key=lambda x: x[1])  # lowest fibre first

            for d, _ in donors:
                for r, _ in receivers:
                    if safe_transfer(d, r, 5.0):
                        adjusted = True
                        break
                if adjusted:
                    break
            if adjusted:
                continue

        # Low fat (and energy not too high) → move from Grain A to oil or higher-fat meat
        if (fat_pct < 12.0 and energy_val < 4500.0) and not adjusted:
            donors = [it for it in ingredient_totals if it["ingredient"] in grain_a_names and it["dm_g"] >= 5.0]
            receivers = [(it, (it["fat_g"] / it["dm_g"]) if it["dm_g"] else 0.0)
                         for it in ingredient_totals
                         if (it["ingredient"] in oil_names_set) or (it["ingredient"] in meat_names_set)]
            receivers.sort(key=lambda x: x[1], reverse=True)
            for d in donors:
                for r, _ in receivers:
                    if safe_transfer(d, r, 5.0):
                        adjusted = True
                        break
                if adjusted:
                    break
            if adjusted:
                continue

        if not adjusted:
            break  # nothing safe to do this pass

    # ---------- Finalize ----------
    totals, _ = compute_macros()

    # drop zero-DM rows
    ingredient_totals = [it for it in ingredient_totals if round(it["dm_g"], 2) > 0.0]

    def pct(key: str) -> float:
        return round(totals[key] * 100.0 / FIXED_TOTAL_DM, 2)

    result = {
        "Protein_percent": pct("Protein"),
        "Fat_percent": pct("Fat"),
        "CHO_percent": pct("CHO"),
        "Fiber_percent": pct("Fiber"),
        "Ash_percent": pct("Ash"),
        "Ca_percent": round(totals["Ca"] * 100.0 / FIXED_TOTAL_DM, 2),
        "P_percent": round(totals["P"] * 100.0 / FIXED_TOTAL_DM, 2),
        "Ca_P_ratio": round(totals["Ca"] / totals["P"], 2) if totals["P"] else 0.0,
        "Energy": round(totals["Energy"], 2),
        "DM_percent": FIXED_TOTAL_DM,
    }

    # Log any out-of-range macros (non-fatal)
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
        "auto_added": None,
    }
