# 🐶 Dog Diet Planner

Plan a balanced dog diet from selected ingredients.

---

## 🛠️ Tech Stack
- **Backend**: Python (FastAPI + Pandas)
- **Frontend**: React.js (Axios)
- **Data**: CSV files (`fixed_ingredients.csv`, `user_ingredients.csv`)

---

## 🧰 Prerequisites
Make sure you have installed:
- Python 3.9+
- Node.js 16+ (with npm)
- Git

---

## 📦 Files expected at repo root
- `fixed_ingredients.csv`
- `user_ingredients.csv`

---

## 🚀 Run the Project (Backend + Frontend)

```bash
# --- Backend setup ---
cd backend
python -m venv .venv
source .venv/bin/activate   # macOS/Linux
# .venv\Scripts\activate    # Windows

pip install -r requirements.txt
uvicorn main:app --reload

# --- Frontend setup ---
cd ../frontend
npm install
npm start
