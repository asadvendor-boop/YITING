# Public Repository Publication Guide

The hackathon requires a public, open-source code repository with all source
code, assets, and instructions needed to run the project. Use this guide after
the final local checks pass and before filling the submission form.

## Required Repository Settings

On the public repository page:

- Visibility: public
- License: detected as MIT from the root `LICENSE` file
- Description: `YITING — Track 3 Agent Society for governed incident response with Qwen`
- Website: the final Alibaba Cloud ECS landing page URL
- Topics:
  - `qwen`
  - `alibaba-cloud`
  - `agent-society`
  - `incident-response`
  - `human-in-the-loop`
  - `fastapi`
  - `nextjs`
  - `hackathon`

The repository About panel should make the track obvious without requiring a
judge to open the README. Use the description above verbatim if possible; it
contains `Track 3 Agent Society` and `Qwen` in the visible repository header.

## Push Checklist

1. Confirm the current tree is clean:

   ```bash
   git status --short
   ```

2. Confirm secrets and runtime artifacts are not tracked:

   ```bash
   git ls-files | grep -E '(^|/)(\.env$|.*\.db$|.*\.db-shm$|.*\.db-wal$|node_modules/|\.next/)'
   ```

   This command should print nothing. If it prints a path, stop and remove that
   tracked artifact before publishing.

3. Configure the public remote:

   ```bash
   git remote add origin <public-repository-url>
   git push -u origin main
   ```

   If `origin` already exists, use:

   ```bash
   git remote set-url origin <public-repository-url>
   git push -u origin main
   ```

4. Verify the remote:

   ```bash
   git remote get-url origin
   ```

5. Open the public repository in a private/incognito browser window and confirm:

   - README renders at the top.
   - `LICENSE` is visible and detected as MIT.
   - `docs/INSTALL_AND_RUN.md` is present.
   - `deploy/alibaba-ecs/README.md` is present.
   - `.env` and local database files are absent.
   - The CI workflow is visible under `.github/workflows/ci.yml`.

## Final Link Usage

Use the public repository URL as `REPO_URL` when finalizing submission links:

Use the final public YouTube, Vimeo, or Facebook Video URL for `VIDEO_URL`.
Use a separate public YouTube, Vimeo, or Facebook Video URL for
`DEPLOYMENT_PROOF_VIDEO_URL`.

```bash
make submission-finalize \
  DOMAIN="https://yiting.47.84.232.193.sslip.io" \
  REPO_URL="<public-repository-url>" \
  VIDEO_URL="https://youtu.be/<video-id>" \
  DEPLOYMENT_PROOF_VIDEO_URL="https://youtu.be/<deployment-proof-video-id>" \
  HERO_INCIDENT_ID="<hero-incident-id>"

python scripts/submission_links.py \
  --repository-url "<public-repository-url>" \
  --live-application-url "https://yiting.47.84.232.193.sslip.io" \
  --demo-video-url "https://youtu.be/<video-id>" \
  --deployment-proof-video-url "https://youtu.be/<deployment-proof-video-id>" \
  --check-reachable
```

Then commit and push the finalized public-link changes before running the final
hosted proof command.
