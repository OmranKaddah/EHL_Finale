# Team evals

An eval is your own world for the challenge: a web app with up to four sites, a task and its one correct answer. The
platform hosts it and runs agents on it, yours or, once you make it public, every team's, each on its own
leaderboard. Use it to test your agent on cases the public scenario doesn't have.

## Quickstart

```sh
atira eval init my-eval          # the starter kit: four sites, a bid configurator, BRIEF.md, expected.json
atira eval dev my-eval           # run it here; each answer is scored against expected.json and printed
atira eval deploy my-eval        # upload it: streams the build, then prints the world's URLs and preview logins
atira eval run my-eval --package submission --repeats 3
atira eval runs my-eval          # mean quality ± sd over the repeats, mean cost and time
atira eval deploy my-eval --public   # every team can run on it; it gets a leaderboard
```

The starter kit is a working eval: four basic sites like the challenge's (tender portal, customer portal, ERP and
mail), a brief and the expected bid. They're deliberately far too simple. Make yours harder, then deploy.

`atira eval dev` starts your app on `127.0.0.1:8710` (8711–8713 for the next sites) with the platform's environment,
`ATIRA_API_URL` pointing at a local stand-in for the platform's two endpoints, and prints a login per site. Open the
URLs in a browser and sign in, or run your agent against them: in another terminal,
`eval "$(atira eval dev --env my-eval)"` exports the run as `CHALLENGE_SCOUTING` with the logins, the way
`atira scout --env` does, so an agent built on the starter kit runs unchanged. Every answer your app hands in is
scored against `expected.json` and printed. Change the app, restart `dev`, try again: nothing is uploaded.

The first `deploy` creates the eval, private, and remembers its id in `my-eval/.atira/eval.json`; every later deploy
pushes a new version. Past runs stay with the version they ran on. In an eval's folder, `<eval>` can be left out of
the other commands; elsewhere give its id (`ev_...`) or slug. Your coding agent gets them as tools through
[`atira mcp`](https://ehl-challenge.atira.ai/docs/mcp.md): `eval_init`, `eval_dev`, `eval_deploy`, `eval_preview`, `eval_run`, `eval_runs` and
`eval_board`, `eval_list`, `eval_status` and `eval_source`.

Other commands: `atira eval ls` lists your evals and the public ones, `atira eval status` shows the versions and the
build log, `atira eval source <eval> --out <dir>` copies a public eval's files into a folder of your own (deploying it
makes a new eval), `atira eval public` and `atira eval private` change who sees it and `atira eval rm` deletes it.

## The bundle

The folder you deploy, with `.gitignore` respected (`.git`, `node_modules` and `.atira` always stay out), at most
50 MB compressed. At its root:

- `atira-eval.json`, the manifest:

  ```json
  { "build": "npm ci", "start": "node server.js", "sites": [{ "name": "portal", "port": 3000 }] }
  ```

  - `build` (optional) runs once when the version is built; `start` starts every site. Both are shell commands run in
    the bundle's folder.
  - `sites`: 1–4 sites, each a `name` (a–z, 0–9 and `-`, starting with a letter, at most 32 characters) and the
    `port` it listens on (1024–65535). Names and ports are unique.
  - `world` (optional) may only be `"shared"`: every eval has one VM, its current version's, for every run and
    preview. Keep each run's state apart: the starter kit keys it by the login's run or preview id.
- `BRIEF.md`: the agent's task, as it reads it after the platform's preamble (at most 64 KB).
- `expected.json`: the correct answer, in the challenge's answer schema (the RFQ bid: `atira challenge rfq` shows it).

See [the world and its contract](#the-world-and-its-contract) for what your app reads and calls.

`deploy` and `dev` check all three files first and name every problem as file → field → problem, e.g.
`atira-eval.json → sites.1.port → must be at least 1024` or `expected.json → positions.0.unit_price → Invalid input:
expected number, received string`.

## Next.js

A `create-next-app` app (App Router, TypeScript, API routes) works as it is, as one site:

```json
{ "build": "npm ci && npm run build", "start": "npm start -- -H 0.0.0.0 -p $PORT_WEB", "sites": [{ "name": "web", "port": 3000 }] }
```

- Keep `package-lock.json` in the folder: `npm ci` needs it.
- `next/font/google` works: a build reaches the package registries and Google Fonts, nothing else, and the running
  app reaches nothing.
- With its `node_modules`, a plain app is about 90 MB compressed (`.next/cache` is left out). The platform keeps a
  built app in parts, up to 400 MB, and every run's world gets all of it. A smaller app starts sooner: with
  `output: "standalone"` in `next.config.ts` the same app is about 12 MB.

  ```json
  {
    "build": "npm ci && npm run build && cp -r public .next/standalone/ && cp -r .next/static .next/standalone/.next/ && rm -rf node_modules",
    "start": "PORT=$PORT_WEB HOSTNAME=0.0.0.0 node .next/standalone/server.js",
    "sites": [{ "name": "web", "port": 3000 }]
  }
  ```

On the platform's machines a fresh `create-next-app` builds in about 15 seconds, answers about a second after it
starts and uses about 130 MB of a world's 2 GB.

## The world and its contract

Each version runs in **one permanent VM, its world**, from the moment its build is ready. Agents and you open its sites
directly on their public URLs; there is no gateway in front. Your app signs agents in and hands their answer in
itself, through two platform endpoints, the way the challenge's own sites do. The starter kit's `atira-kit.js` does
both: copy it into your app.

The app starts with, `<NAME>` being the site's name upper-cased with `_` for `-`:

| Variable | What |
| --- | --- |
| `PORT_<NAME>` | the port to listen on; use it rather than the manifest's |
| `ATIRA_SITE_URL_<NAME>` | the site's own public URL, for links between your sites |
| `ATIRA_API_URL` | the platform API's origin, the only host the world reaches |
| `ATIRA_EVAL_TOKEN` | a secret bearer for this version only |

Each run's agent gets a login per site (username `u_…`, a password), as on the challenge's sites; a preview's are
`p_…`. Both endpoints take `Authorization: Bearer $ATIRA_EVAL_TOKEN` and JSON:

- `POST $ATIRA_API_URL/v1/eval-worlds/verify` `{"site": "portal", "username": "u_…", "password": "…"}`: 200
  `{"run_id": "run_…", "expires_at": 1760001200000}` (`preview_id` for a preview), else 401. Keep the session in a
  signed cookie and ask again at most every 10 s, so an ended run is signed out.
- `POST $ATIRA_API_URL/v1/eval-worlds/answer` `{"run_id": "run_…", "bid": {…}}` (or `preview_id`): for a run `202`
  and the run ends; for a preview `200` `{"accepted": true, "score": {"quality", "eligible", "breakdown"}}` and you can
  submit again; `400` `{"issues": [{"path", "message"}]}` for a bid that fails the answer schema, so the page can show
  them and the agent can try again; `409` once the run has its answer.

`atira eval dev` serves both endpoints locally with the same paths, fields and env.

### Next.js

Copy `atira-kit.js` next to your app (it is plain Node, ESM), then a sign-in route, a guard and an answer route:

```ts
// app/login/route.ts: POST username, password (and returnTo) from your login page's form
import { signIn } from "@/atira-kit.js"
export async function POST(request: Request) {
  const form = await request.formData()
  const signed = await signIn("web", String(form.get("username")), String(form.get("password")), true)
  if (!signed) return Response.redirect(new URL("/login?error=1", request.url), 303)
  return new Response(null, { status: 303, headers: { location: "/", "set-cookie": signed.cookie } })
}

// in a server component or route handler: the login, or off to /login
import { cookies } from "next/headers"
import { redirect } from "next/navigation"
import { currentLogin } from "@/atira-kit.js"
const login = await currentLogin((await cookies()).toString(), "web")
if (!login) redirect("/login")

// app/answer/route.ts: the browser POSTs the bid here; the app hands it to the platform
import { currentLogin, submitAnswer } from "@/atira-kit.js"
export async function POST(request: Request) {
  const login = await currentLogin(request.headers.get("cookie"), "web")
  if (!login) return Response.json({ error: "Bitte anmelden." }, { status: 401 })
  const { status, body } = await submitAnswer(login, await request.json())
  return Response.json(body, { status })
}
```

Run it on the Node.js runtime (the default), not the Edge runtime: the kit uses `node:crypto`. With Express,
`guard(req, res, "web")` from the kit serves `/login` and `/logout` and returns the login (or null once it has
answered), as the starter kit's `server.js` does.

## The answer

It is scored with the main challenge's scorer, against your `expected.json`: the decision must match; then the tender
reference 5 points, the discount 5, the net total 15 (it must also be the sum of the lines) and 75 for the positions,
shared equally, each split into material 35 %, quantity 20 %, unit price 30 % and lead time 15 %. A line for a
position your answer doesn't have costs one position's share. Breakdown fields such as `base_unit_price` are
accepted and not scored.

## Runs, previews and leaderboards

- `atira eval preview` gives you logins per site on the eval's one world for a few hours (`--hours`, 1–8), at once;
  nothing boots for it, and the world is never restarted on request. A bid you submit there is scored against
  `expected.json`.
- `atira eval run` runs a package: your latest submission's (`--package submission`, the default), your latest test
  run's (`test`), any earlier submission's or run's of your team by its id (`--package sub_...` or `run_...`, scored or
  not, as long as its package is still stored), or a folder (`--package ./my-agent`), 1–3 times (`--repeats`). Name an
  entry with `--label`, or later with `atira run name <run> "name"` (only your team sees names). Each run is an ordinary run: its page,
  logs, screenshots and `diagnose_run` work as for test runs, with the scored run's 20-minute limit.
- Private evals (the default) are yours alone, their runs too: a run's page and logs answer 404 to anyone outside your
  team. Public ones: any team runs on them and reads their source, `expected.json`
  included. Each version has its own leaderboard (`atira eval board`): each team's best entry, by mean quality, then
  cost × time.

Limits, unless the organizers change them: 10 evals a team and 12 eval runs an hour (each repeat counts), and
previews for up to 8 hours. Eval runs share your team's test-run limit: up to 15 test and eval
runs at a time and 12 waiting, together.

## Security

- The world reaches only the platform's API (`ATIRA_API_URL`): everything else it needs is in the bundle or made by
  `build`.
- Every page should need a login: the sites are on public URLs. The starter kit's `atira-kit.js` does it, verifying
  each login with the platform.
- A public eval's source is public, `expected.json` included: never put a secret in it. `ATIRA_EVAL_TOKEN` comes from
  the environment, never from the bundle.
- A private eval's sites get unguessable URLs; a public eval's are named after its slug.
- One world serves every run of the version: keep each run's state apart (by its run id).
