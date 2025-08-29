import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";

const API_BASE = "http://127.0.0.1:8000";

export default function App() {
  const [ingredients, setIngredients] = useState([]); // [{ingredient_name, group_name}]
  const [selected, setSelected] = useState(new Set());
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState("");

  // Load & normalize
  useEffect(() => {
    axios
      .get(`${API_BASE}/user-ingredients`)
      .then((res) => {
        const raw = res.data || [];
        const normalized = raw
          .map((row) => {
            if (typeof row === "string") {
              const name = row?.trim();
              return name ? { ingredient_name: name, group_name: "Other" } : null;
            }
            const name =
              (row?.ingredient_name ?? row?.name ?? "").toString().trim();
            if (!name) return null;
            const group = (row?.group_name ?? "Other").toString().trim();
            return { ingredient_name: name, group_name: group };
          })
          .filter(Boolean);
        setIngredients(normalized);
        setFetchError("");
      })
      .catch(() => setFetchError("Failed to load ingredients"));
  }, []);

  // Group safely
  const grouped = useMemo(() => {
    const g = {};
    for (const ing of ingredients) {
      const group = (ing?.group_name || "Other").toString();
      if (!g[group]) g[group] = [];
      g[group].push(ing);
    }
    for (const k of Object.keys(g)) {
      g[k].sort((a, b) =>
        (a?.ingredient_name || "").localeCompare(b?.ingredient_name || "")
      );
    }
    return Object.fromEntries(
      Object.entries(g).sort(([a], [b]) => (a || "").localeCompare(b || ""))
    );
  }, [ingredients]);

  const toggleOne = (name, checked) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(name);
      else next.delete(name);
      return next;
    });
  };

  const toggleGroup = (items, checked) => {
    const names = items.map((i) => i.ingredient_name).filter(Boolean);
    setSelected((prev) => {
      const next = new Set(prev);
      for (const n of names) checked ? next.add(n) : next.delete(n);
      return next;
    });
  };

  const selectedList = useMemo(() => Array.from(selected), [selected]);

  const calculate = async () => {
    if (!selected.size) {
      alert("Select at least one ingredient");
      return;
    }
    setLoading(true);
    setResult(null);
    try {
      const res = await axios.post(`${API_BASE}/calculate`, {
        ingredients: selectedList,
      });
      setResult(res.data);
    } catch (e) {
      console.error(e);
      alert("Error calculating diet (check backend logs).");
    } finally {
      setLoading(false);
    }
  };

  const totals = useMemo(() => {
    const init = {
      dm_g: 0,
      protein_g: 0,
      fat_g: 0,
      cho_g: 0,
      fiber_g: 0,
      ash_g: 0,
      ca_mg: 0,
      p_mg: 0,
      iron_mg: 0,
      energy_kcal: 0,
    };
    const rows = result?.ingredient_totals || [];
    return rows.reduce((acc, it) => {
      acc.dm_g += +it?.dm_g || 0;
      acc.protein_g += +it?.protein_g || 0;
      acc.fat_g += +it?.fat_g || 0;
      acc.cho_g += +it?.cho_g || 0;
      acc.fiber_g += +it?.fiber_g || 0;
      acc.ash_g += +it?.ash_g || 0;
      acc.ca_mg += +it?.ca_mg || 0;
      acc.p_mg += +it?.p_mg || 0;
      acc.iron_mg += +it?.iron_mg || 0;
      acc.energy_kcal += +it?.energy_kcal || 0;
      return acc;
    }, init);
  }, [result]);

  return (
    <div style={{ padding: 20, fontFamily: "Inter, Arial, sans-serif" }}>
      <h1 style={{ marginBottom: 10 }}>🐶 Dog Diet Planner</h1>

      {fetchError && (
        <div
          style={{
            background: "#fee2e2",
            color: "#991b1b",
            padding: 8,
            borderRadius: 6,
          }}
        >
          {fetchError}
        </div>
      )}

      <h2 style={{ margin: "14px 0" }}>1) Select Ingredients</h2>
      {Object.entries(grouped).map(([group, items]) => {
        const allChecked = items.every((i) => selected.has(i.ingredient_name));
        const someChecked =
          !allChecked && items.some((i) => selected.has(i.ingredient_name));
        return (
          <fieldset
            key={group}
            style={{
              border: "1px solid #e5e7eb",
              borderRadius: 8,
              padding: 10,
              marginBottom: 12,
            }}
          >
            <legend
              style={{
                fontWeight: 600,
                background: "#fff7ed",
                padding: "2px 8px",
                borderRadius: 6,
              }}
            >
              {group || "Other"}
            </legend>

            <label
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                marginBottom: 8,
              }}
            >
              <input
                type="checkbox"
                checked={allChecked}
                ref={(el) => {
                  if (el) el.indeterminate = someChecked;
                }}
                onChange={(e) => toggleGroup(items, e.target.checked)}
              />
              <span style={{ fontSize: 12, color: "#6b7280" }}>Select all</span>
            </label>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(220px,1fr))",
                gap: 8,
              }}
            >
              {items.map((it) => (
                <label
                  key={it.ingredient_name}
                  style={{
                    border: "1px solid #16a34a",
                    borderRadius: 8,
                    padding: 8,
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    background: selected.has(it.ingredient_name)
                      ? "#ecfdf5"
                      : "white",
                  }}
                >
                  <input
                    type="checkbox"
                    checked={selected.has(it.ingredient_name)}
                    onChange={(e) => toggleOne(it.ingredient_name, e.target.checked)}
                  />
                  <span>{it.ingredient_name}</span>
                </label>
              ))}
            </div>
          </fieldset>
        );
      })}

      <div style={{ display: "flex", gap: 10, marginBottom: 16 }}>
        <button
          onClick={calculate}
          disabled={loading || !ingredients.length}
          style={{
            padding: "10px 16px",
            background: loading ? "#9ca3af" : "#16a34a",
            color: "#fff",
            border: "none",
            borderRadius: 6,
            cursor: loading ? "not-allowed" : "pointer",
          }}
        >
          {loading ? "Calculating..." : "🧮 Calculate Diet"}
        </button>
        <button
          onClick={() => {
            setSelected(new Set());
            setResult(null);
          }}
          style={{
            padding: "10px 14px",
            background: "#f3f4f6",
            border: "1px solid #e5e7eb",
            borderRadius: 6,
          }}
        >
          Reset
        </button>
      </div>

      {result && (
        <div>
          <h2>2) Nutrient Summary</h2>
          <ul style={{ lineHeight: 1.8 }}>
            {Object.entries(result.nutrient_percentages || {}).map(([k, v]) => (
              <li key={k}>
                {k.replace(/_/g, " ")}: <strong>{v}</strong>
              </li>
            ))}
          </ul>

          <div style={{ marginTop: 16 }}>
            <h3>📌 Fixed Ingredients (DM g)</h3>
            <ul>
              {(result.dm_breakdown || [])
                .filter((d) => d.fixed)
                .map((d, i) => (
                  <li key={`fx-${i}`}>
                    {d.ingredient}: {d.dm_g} g
                  </li>
                ))}
            </ul>

            <h3 style={{ marginTop: 10 }}>📋 Selected Ingredients (DM g)</h3>
            <ul>
              {(result.dm_breakdown || [])
                .filter((d) => !d.fixed)
                .map((d, i) => (
                  <li key={`sl-${i}`}>
                    {d.ingredient}: {d.dm_g} g
                  </li>
                ))}
            </ul>
          </div>

          <div style={{ marginTop: 20, overflowX: "auto" }}>
            <h3>📘 Ingredient-wise Nutrient Contribution</h3>
            <table style={{ borderCollapse: "collapse", minWidth: 900 }}>
              <thead>
                <tr>
                  {[
                    "Ingredient",
                    "DM (g)",
                    "Protein (g)",
                    "Fat (g)",
                    "CHO (g)",
                    "Fiber (g)",
                    "Ash (g)",
                    "Ca (mg)",
                    "P (mg)",
                    "Iron (mg)",
                    "Energy (kcal)",
                  ].map((h) => (
                    <th
                      key={h}
                      style={{
                        border: "1px solid #d1d5db",
                        padding: 6,
                        background: "#f3f4f6",
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(result.ingredient_totals || []).map((it, i) => (
                  <tr key={i}>
                    <td style={{ border: "1px solid #e5e7eb", padding: 6 }}>
                      {it.ingredient}
                    </td>
                    <td style={{ border: "1px solid #e5e7eb", padding: 6 }}>
                      {it.dm_g}
                    </td>
                    <td style={{ border: "1px solid #e5e7eb", padding: 6 }}>
                      {it.protein_g}
                    </td>
                    <td style={{ border: "1px solid #e5e7eb", padding: 6 }}>
                      {it.fat_g}
                    </td>
                    <td style={{ border: "1px solid #e5e7eb", padding: 6 }}>
                      {it.cho_g}
                    </td>
                    <td style={{ border: "1px solid #e5e7eb", padding: 6 }}>
                      {it.fiber_g}
                    </td>
                    <td style={{ border: "1px solid #e5e7eb", padding: 6 }}>
                      {it.ash_g}
                    </td>
                    <td style={{ border: "1px solid #e5e7eb", padding: 6 }}>
                      {it.ca_mg}
                    </td>
                    <td style={{ border: "1px solid #e5e7eb", padding: 6 }}>
                      {it.p_mg}
                    </td>
                    <td style={{ border: "1px solid #e5e7eb", padding: 6 }}>
                      {it.iron_mg}
                    </td>
                    <td style={{ border: "1px solid #e5e7eb", padding: 6 }}>
                      {it.energy_kcal}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr style={{ background: "#eff6ff", fontWeight: 600 }}>
                  <td style={{ border: "1px solid #e5e7eb", padding: 6 }}>
                    Total
                  </td>
                  <td style={{ border: "1px solid #e5e7eb", padding: 6 }}>
                    {totals.dm_g.toFixed(2)}
                  </td>
                  <td style={{ border: "1px solid #e5e7eb", padding: 6 }}>
                    {totals.protein_g.toFixed(2)}
                  </td>
                  <td style={{ border: "1px solid #e5e7eb", padding: 6 }}>
                    {totals.fat_g.toFixed(2)}
                  </td>
                  <td style={{ border: "1px solid #e5e7eb", padding: 6 }}>
                    {totals.cho_g.toFixed(2)}
                  </td>
                  <td style={{ border: "1px solid #e5e7eb", padding: 6 }}>
                    {totals.fiber_g.toFixed(2)}
                  </td>
                  <td style={{ border: "1px solid #e5e7eb", padding: 6 }}>
                    {totals.ash_g.toFixed(2)}
                  </td>
                  <td style={{ border: "1px solid #e5e7eb", padding: 6 }}>
                    {totals.ca_mg.toFixed(2)}
                  </td>
                  <td style={{ border: "1px solid #e5e7eb", padding: 6 }}>
                    {totals.p_mg.toFixed(2)}
                  </td>
                  <td style={{ border: "1px solid #e5e7eb", padding: 6 }}>
                    {totals.iron_mg.toFixed(2)}
                  </td>
                  <td style={{ border: "1px solid #e5e7eb", padding: 6 }}>
                    {totals.energy_kcal.toFixed(2)}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>

          {!!(result?.issues?.length) && (
            <div
              style={{
                marginTop: 12,
                background: "#fff7ed",
                color: "#9a3412",
                padding: 10,
                borderRadius: 6,
              }}
            >
              <strong>Issues:</strong>
              <ul>{result.issues.map((m, i) => <li key={i}>• {m}</li>)}</ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
