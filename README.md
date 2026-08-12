# 🐶 Dog Diet Planner

A full-stack rule-based dog diet planning application for selecting ingredients, calculating a 1000 g dry-matter diet, analysing nutrient contributions, and identifying nutrient-range issues through an interactive React interface.

**Live Application:** Coming Soon
**GitHub:** https://github.com/mamathabyreddy99/dog-diet
**Developer:** Mamatha Byreddy
**LinkedIn:** https://www.linkedin.com/in/byreddy-mamatha-296a221a8

---

# Project Overview

Dog Diet Planner is a full-stack application that helps users build a structured dog diet from selected ingredients.

The application combines a **React frontend**, **FastAPI backend**, **Pandas-based data processing**, and CSV ingredient datasets.

Users select ingredients through the web interface, and the backend applies a rule-based diet allocation process to calculate ingredient quantities, nutrient contributions, nutrient percentages, energy, calcium-to-phosphorus ratio, and possible diet issues.

The application normalizes the final diet to a fixed target of **1000 g dry matter (DM)**.

---

# Features

## Ingredient Selection

The application loads available ingredients from the backend and groups them by ingredient category.

Users can:

* select individual ingredients;
* select or deselect an entire ingredient group;
* reset the current selection;
* calculate a diet from the selected ingredients.

The frontend prevents calculation until at least one ingredient has been selected.

---

## Diet Calculation

Selected ingredients are sent from the React frontend to the FastAPI backend.

The backend applies ingredient-group rules for:

* organs;
* oils;
* vegetables;
* grains;
* meat.

The resulting ingredient allocations are normalized to a total of **1000 g dry matter**.

---

## Nutrient Analysis

The application calculates:

* Protein;
* Fat;
* Carbohydrates (CHO);
* Fiber;
* Ash;
* Calcium;
* Phosphorus;
* Iron;
* Energy.

The final result also includes:

* protein percentage;
* fat percentage;
* CHO percentage;
* fiber percentage;
* ash percentage;
* calcium percentage;
* phosphorus percentage;
* calcium-to-phosphorus ratio;
* total energy;
* dry-matter percentage.

---

## Ingredient-Level Nutrient Contribution

The interface provides a detailed nutrient contribution table for every ingredient in the calculated diet.

Displayed values include:

* dry matter (g);
* protein (g);
* fat (g);
* carbohydrate (g);
* fiber (g);
* ash (g);
* calcium (mg);
* phosphorus (mg);
* iron (mg);
* energy (kcal).

A total row is calculated across all ingredients.

---

## Diet Warnings

The backend performs non-fatal nutrient-range checks.

The current implementation checks whether:

* Protein is within 32–40%;
* Fat is within 12–17%;
* Fiber is within 3–6%;
* Energy is within 4000–4500 kcal.

If a calculated diet falls outside one of these configured ranges, the application returns an issue message that is displayed in the frontend.

---

# Diet Planning Rules

The backend contains explicit rule-based allocation logic.

## Organs

* Liver only → 120 g
* Liver with other organ selections → liver 100 g
* Additional organs → 50 g total

---

## Oils

* Oil allocation → 10 g total
* Salmon oil receives special handling when selected

---

## Vegetables

* Vegetable A only → 80 g
* Vegetable B only → 70 g
* Vegetable A + B → 70 g + 30 g
* Vegetable C / potato → maximum 100 g

---

## Grains

When potato is selected:

```text
Total Grain A + Grain B
→ 200–300 g
```

When potato is not selected:

```text
Total Grain A + Grain B
→ 300–400 g
```

Grain B is targeted within:

```text
140–200 g
```

Grain A fills the remaining grain window with a per-item cap.

---

## Meat

The default meat target is approximately:

```text
280 g
```

and is constrained by available dry matter and configured limits.

Special cases include:

* Meat-C-only selection;
* Meat-B-only selection;
* automatic lean Meat-A addition;
* Meat-B maximum allocation;
* special Meat-A limits for egg white, shrimp, and oyster.

---

# Post-Calculation Adjustment Rules

After the initial ingredient allocation, the application applies additional rules.

## High Protein

If protein exceeds 40%:

```text
Move part of the diet
from Meat-A
to Grain A or Grain B
```

---

## Low Protein

If protein is below 32%:

```text
Increase Meat-B allocation
while respecting configured limits
```

---

## Low Fat

If fat is below 12%:

```text
Increase Meat-B allocation
up to its configured maximum
```

After adjustment, the diet is normalized again to:

```text
1000 g dry matter
```

---

# Data Processing

The application uses two CSV datasets located at the repository root.

## `fixed_ingredients.csv`

Contains fixed ingredient data.

Expected columns include:

```text
ingredient_name
dm_g
protein_g
fat_g
cho_g
fiber_g
ash_g
calcium_mg
phosphorus_mg
iron_mg
energy_kcal
```

---

## `user_ingredients.csv`

Contains selectable ingredient data and ingredient groups.

Expected columns include:

```text
ingredient_name
group_name
protein_g
fat_g
cho_g
fiber_g
ash_g
calcium_mg
phosphorus_mg
iron_mg
energy_kcal
```

---

# CSV Validation

CSV files are validated when loaded.

If required columns are missing, the backend raises an error identifying the missing fields.

The application stores the loaded datasets in memory after successful validation.

CSV data can also be reloaded through the API.

---

# Backend API

The backend is built with FastAPI.

## Root

```http
GET /
```

Returns a message confirming that the Dog Diet Planner API is running.

---

## Get User Ingredients

```http
GET /user-ingredients
```

Returns ingredient names and group names for the frontend.

Example response:

```json
[
  {
    "ingredient_name": "Example Ingredient",
    "group_name": "Example Group"
  }
]
```

---

## Calculate Diet

```http
POST /calculate
```

Example request:

```json
{
  "ingredients": [
    "Ingredient A",
    "Ingredient B"
  ]
}
```

The backend processes the selections and returns:

* nutrient percentages;
* dry-matter breakdown;
* ingredient-level totals;
* warnings/issues;
* automatically added ingredients when applicable.

---

## Reload CSV Data

```http
POST /reload
```

Reloads both CSV datasets into memory.

---

# Frontend Workflow

The React frontend communicates with FastAPI using Axios.

```text
Application Load
      ↓
GET /user-ingredients
      ↓
Normalize Ingredient Data
      ↓
Group Ingredients by Category
      ↓
User Selects Ingredients
      ↓
POST /calculate
      ↓
FastAPI Diet Engine
      ↓
Nutrient Calculations
      ↓
React Results Display
```

---

# Application Architecture

```text
                    User
                      │
                      ▼
              React.js Frontend
                      │
          Ingredient Selection UI
                      │
                      ▼
                    Axios
                      │
                      ▼
               FastAPI Backend
                      │
        ┌─────────────┴─────────────┐
        │                           │
        ▼                           ▼
 Ingredient Selection        Diet Calculation
      Endpoint                    Engine
        │                           │
        │                           ▼
        │                      Pandas
        │                           │
        │                 CSV Data Processing
        │                           │
        └──────────────┬────────────┘
                       ▼
                Structured Result
                       │
                       ▼
                React Results UI
                       │
         ┌─────────────┼─────────────┐
         │             │             │
         ▼             ▼             ▼
 Nutrient Summary   DM Breakdown   Nutrient Table
                                      │
                                      ▼
                                 Diet Warnings
```

---

# Important Engineering Decisions

## Fixed Dry-Matter Target

The diet engine uses:

```text
1000 g
```

as the fixed dry-matter target.

Ingredient allocations are adjusted relative to this target.

---

## Rule-Based Allocation

Diet composition is determined through explicit Python rules rather than random allocation.

Different ingredient groups have different quantity limits and allocation behaviour.

---

## Nutrient Contribution Is Calculated Per Ingredient

Ingredient nutrient values are stored per 100 g.

For each ingredient allocation, nutrient contribution is calculated proportionally based on the assigned dry-matter quantity.

---

## Frontend and Backend Responsibilities Are Separated

The React frontend handles:

* ingredient selection;
* grouping;
* loading states;
* result presentation;
* user interaction.

The FastAPI backend handles:

* CSV loading;
* validation;
* diet rules;
* nutrient calculations;
* warnings;
* result generation.

---

## CSV Structure Is Validated

Both datasets are checked for required columns before use.

This prevents the calculation workflow from silently operating on incomplete input data.

---

# Technology Stack

* Python
* FastAPI
* Pandas
* Pydantic
* Uvicorn
* React.js
* JavaScript
* Axios
* CSV

---

# Project Structure

```text
dog-diet/
│
├── backend/
│   ├── __init__.py
│   ├── main.py
│   │
│   ├── routers/
│   │   ├── __init__.py
│   │   └── diet_router.py
│   │
│   └── services/
│       ├── __init__.py
│       └── diet_service.py
│
├── frontend/
│   ├── public/
│   │
│   ├── src/
│   │   ├── App.js
│   │   ├── App.css
│   │   ├── App.test.js
│   │   ├── index.js
│   │   └── index.css
│   │
│   ├── package.json
│   └── package-lock.json
│
├── fixed_ingredients.csv
├── user_ingredients.csv
├── requirements.txt
├── .gitignore
└── README.md
```

---

# Installation

## Clone the Repository

```bash
git clone https://github.com/mamathabyreddy99/dog-diet.git
```

```bash
cd dog-diet
```

---

# Backend Setup

Create a virtual environment.

## macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## Windows

```bash
python -m venv .venv
.venv\Scripts\activate
```

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Start the FastAPI backend:

```bash
uvicorn backend.main:app --reload
```

The backend runs locally on:

```text
http://127.0.0.1:8000
```

---

# Frontend Setup

Open a second terminal.

```bash
cd frontend
```

Install dependencies:

```bash
npm install
```

Start the React application:

```bash
npm start
```

The frontend normally runs on:

```text
http://localhost:3000
```

---

# Example Workflow

```text
Start Backend
      ↓
Start React Frontend
      ↓
Load Ingredient Groups
      ↓
Select Ingredients
      ↓
Click Calculate Diet
      ↓
Send Ingredient List to FastAPI
      ↓
Apply Diet Allocation Rules
      ↓
Calculate Nutrient Contributions
      ↓
Normalize to 1000 g DM
      ↓
Apply Post-Calculation Rules
      ↓
Generate Nutrient Percentages
      ↓
Generate Ingredient-Level Breakdown
      ↓
Check Nutrient Ranges
      ↓
Display Results and Issues
```

---

# Current Limitations

* The application uses rule-based diet allocation rather than optimization-based formulation.
* Ingredient data is stored in CSV files rather than a database.
* The frontend currently points to a local FastAPI URL.
* User authentication is not implemented.
* Diet history is not stored.
* Nutrient targets and ingredient-allocation rules are currently defined in application logic.
* The application is not a substitute for professional veterinary nutritional guidance.

---

# Future Improvements

* Database integration
* User accounts and authentication
* Saved diet plans
* Configurable dog profile information
* Weight- and activity-based diet calculation
* More flexible nutrient targets
* Expanded ingredient database
* Automated diet optimization
* Improved responsive UI
* Data visualisation
* Backend and frontend deployment
* Automated API and calculation tests
* Docker support

---

# Author

**Mamatha Byreddy**

Interested in applied AI, machine learning, data engineering, and software development.

**GitHub:** `mamathabyreddy99`

**LinkedIn:** https://www.linkedin.com/in/byreddy-mamatha-296a221a8

---

# License

Add a project license before external distribution or reuse.
