# Local frontend

This barebones React and Monaco UI exercises the existing local API. It supports the prebuilt problem catalog, workspace loading and saving, visible-test runs, hidden-test submissions, job polling, and submission history. It does not call a generation service.

From the repository root, start the API in one terminal (Docker is required for run and submit):

```sh
make api-local
```

In another terminal:

```sh
cd frontend
npm install
npm run dev
```

Open the URL printed by Vite and paste the local bearer token printed by `make api-local`. The token stays in page memory and is cleared on reload. The Vite dev server proxies `/api` to `http://127.0.0.1:8080`; set `VITE_API_BASE_URL` for another same-origin API base URL. Monaco and its editor worker are bundled locally. The token is sent as an Authorization header, never as a user ID.

Run `npm run build` and `npm test` for frontend checks. The UI uses visible problem data only; submit results show verdicts and counts without hidden-test details.
