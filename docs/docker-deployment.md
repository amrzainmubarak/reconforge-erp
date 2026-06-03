# Docker Deployment

ReconForge ERP can be packaged in a local Docker image for repeatable command-line use. The Dockerfile is intentionally simple: it installs the local package and includes the repository's config, examples, docs, and control packs.

This page documents commands for local verification. If Docker is not available in the environment, treat this as an inspection and manual verification checklist rather than a runtime-verified result.

## Build

```bash
docker build -t reconforge-erp .
```

## Run Doctor

Linux/macOS Bash:

```bash
docker run --rm -v ${PWD}/output:/app/output reconforge-erp reconforge doctor
```

Windows PowerShell:

```powershell
docker run --rm -v ${PWD}/output:/app/output reconforge-erp reconforge doctor
```

Windows Command Prompt:

```cmd
docker run --rm -v %cd%\output:/app/output reconforge-erp reconforge doctor
```

## Run The Demo

Linux/macOS Bash:

```bash
docker run --rm -v ${PWD}/output:/app/output reconforge-erp reconforge demo run --output output/demo
```

Windows PowerShell:

```powershell
docker run --rm -v ${PWD}/output:/app/output reconforge-erp reconforge demo run --output output/demo
```

Generated files will appear under the local `output/` folder mounted into the container.

## Docker Desktop Notes

- Start Docker Desktop before running build or run commands.
- On Windows, keep the repository in a shared drive/location that Docker Desktop can mount.
- If WSL cannot reach Docker, confirm Docker Desktop WSL integration is enabled for the distro.
- Use PowerShell commands from the repository root unless you intentionally change the mounted folder.

## Docker Compose

If `docker-compose.yml` is present:

```bash
docker compose build
docker compose run --rm reconforge reconforge doctor
docker compose run --rm reconforge reconforge demo run --output output/demo
```

The dashboard service exposes the local dashboard on port `8501`:

```bash
docker compose up dashboard
```

## Security Notes

- Keep ERP exports mounted only into folders needed by the command.
- Do not mount broad home directories into the container.
- Review generated evidence folders before sharing them outside the engagement team.
- The container does not add authentication or access control.
- Local host file permissions still matter.

## Verification Checklist

Before claiming Docker runtime verification for a release, run:

```bash
docker build -t reconforge-erp .
docker run --rm -v ${PWD}/output:/app/output reconforge-erp reconforge doctor
docker run --rm -v ${PWD}/output:/app/output reconforge-erp reconforge demo run --output output/demo
```

Record the Docker version, operating system, and command output in the release notes or maintainer notes.

## Common Troubleshooting

| Symptom | Likely Cause | Suggested Action |
| --- | --- | --- |
| `Cannot connect to the Docker daemon` | Docker Desktop or Docker Engine is not running | Start Docker and rerun `docker version`. |
| Files are not written to `output/` | Volume path is wrong or Docker cannot mount the folder | Run from the repository root and confirm the local `output/` path exists or can be created. |
| `reconforge: command not found` inside container | Image was not rebuilt after local changes | Rerun `docker build -t reconforge-erp .`. |
| Permission errors on Linux | Host user permissions on mounted `output/` | Check owner/mode of `output/` or run with an appropriate user mapping for your environment. |

## Current Verification Status

See [Docker Verification Report](strategy/docker-verification-report.md). ReconForge ERP v0.6.1 includes Docker build workflow support and deployment documentation, but Docker runtime verification is not claimed unless Docker Desktop or Docker Engine is running and the documented build/run commands pass.
