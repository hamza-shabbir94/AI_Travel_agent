# AI Travel Advisor: FastAPI + React

```
travel-advisor-web/
├── backend/            FastAPI (Python): the AI travel agent
│   ├── advisor.py      the agent: prompt, tools, plan, images, costs
│   ├── index.py        the API: GET /health, POST /chat
│   ├── requirements.txt
│   └── vercel.json     allows up to 120 s per request
└── frontend/           React (Vite): the chat page
    ├── index.html
    ├── package.json
    └── src/
        ├── App.jsx     the chat page
        ├── App.css     the styles
        └── main.jsx    starts React
```

The browser (React) sends each message to the backend (FastAPI), which talks to OpenAI.
OpenAI stores the conversation; the browser only keeps the last `response_id`.

## 1. Run it on your computer

You need Anaconda (or Miniconda) and Node.js (`node -v` should work; if not, install it from nodejs.org).

**One-time setup: create the Python environment**

```bash
conda deactivate                         # make sure (base) is off
conda create -n travel python=3.12 -y    # 3.12 = Vercel's default Python
conda activate travel
cd backend
python -m pip install -r requirements.txt
cp .env.example .env                     # put your OpenAI key in .env
```

**Terminal 1: backend**

```bash
conda activate travel
cd backend
python -m uvicorn index:app
```

Wait for `Application startup complete.` Then check:
http://localhost:8000/health shows `{"status":"ok"}`, and http://localhost:8000/docs lets you try `/chat`.

Test from another terminal (or Postman: POST, Body → raw → JSON):

```bash
curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -d '{"message": "3 days in Berlin, food and nightlife", "generate_image": false}'
```

To continue the chat, send the `response_id` from the answer as `"previous_response_id"`.

**Environment rules**

- Your prompt must show **only** `(travel)`. Two names like `(.venv) (base)` mix two Pythons and can crash with `segmentation fault`.
- Check with `which python`: the path must contain `envs/travel`.
- Every new terminal starts outside the environment: run `conda activate travel` again.
- In VS Code: Cmd+Shift+P → **Python: Select Interpreter** → `travel`.

**Terminal 2: frontend**

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and chat.

## 2. Put the code on GitHub

```bash
cd travel-advisor-web
git init
git add .
git commit -m "AI travel advisor"
```

Create an empty repository on github.com, then follow the two commands GitHub shows
(`git remote add origin ...` and `git push -u origin main`).
Check on GitHub that **no `.env` file** was uploaded.

## 3. Deploy to Vercel (two projects from the same repository)

**Backend**

1. vercel.com → **Add New… → Project** → import your repository.
2. **Root Directory:** `backend`. Vercel detects FastAPI by itself.
3. **Environment Variables:** `OPENAI_API_KEY` = your key.
4. **Deploy.** Copy the URL, e.g. `https://travel-advisor-backend.vercel.app`.
5. Test: open `<that URL>/health`.

**Frontend**

1. **Add New… → Project** → import the **same** repository again.
2. **Root Directory:** `frontend`. Vercel detects Vite by itself.
3. **Environment Variables:** `VITE_API_URL` = the backend URL from above (no `/` at the end).
4. **Deploy.** Open the frontend URL and chat.

**Lock the backend to your frontend (recommended)**

Backend project → Settings → Environment Variables → add `FRONTEND_URL` = your frontend URL
→ Deployments → **Redeploy**. Now only your page can call the API from a browser.

## Things to know

- **Costs:** every message uses your OpenAI key. Set a monthly budget limit in the OpenAI
  dashboard, and don't share the backend URL publicly.
- **Changes:** after `git push`, Vercel redeploys both projects automatically.
- **Changed `VITE_API_URL`?** Redeploy the frontend; Vite reads it at build time.
- **Slow replies:** a plan with tools and an image can take 30–60 seconds.

## Troubleshooting

| Problem | Cause | Fix |
| --- | --- | --- |
| `segmentation fault` | Two environments active at once, e.g. `(.venv) (base)` | `conda deactivate` until no name shows, then `conda activate travel` |
| `No module named 'fastapi'` | Wrong environment, or packages not installed | `conda activate travel`, then `python -m pip install -r requirements.txt` |
| `422` with `"loc": ["body"]` | The request has no JSON body | Send `{"message": "..."}` as raw JSON |
| `403 Forbidden` on port 8501 | 8501 is Streamlit, not this API | The API runs on port **8000** |
| `curl: Failed to connect` | The backend isn't running yet | Start it and wait for `Application startup complete.` |
| Want auto-restart on save | Off by default | `python -m uvicorn index:app --reload` |
