# Docker Deployment

ReconForge ERP can be packaged in a local Docker image for repeatable command-line use. The Dockerfile is intentionally simple: it installs the local package and includes the repository's config, examples, docs, and control packs.

This page documents commands for local verification. If Docker is not available in the environment, treat this as an inspection and manual verification checklist rather than a runtime-verified result.

## Build

```bash
docker build -t reconforge-erp .
```

## Run Doctor

Bash:

```bash
docker run --rm -v ${PWD}/output:/app/output reconforge-erp reconforge doctor
```

PowerShell:

```powershell
docker run --rm -v ${PWD}/output:/app/output reconforge-erp reconforge doctor
```

## Run The Demo

```bash
docker run --rm -v ${PWD}/output:/app/output reconforge-erp reconforge demo run --output output/demo
```

Generated files will appear under the local `output/` folder mounted into the container.

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
