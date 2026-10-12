# Archived upstream source, built only as a disposable synthetic CI fixture.
FROM golang:1.27.1-bookworm@sha256:69a7b9788769bec032d238959b61854e9ae87f57be9029ec04e9885fabf99195 AS build
WORKDIR /src
ENV CGO_ENABLED=0 GOTOOLCHAIN=local GOMAXPROCS=2 GOPROXY=https://proxy.golang.org GOSUMDB=sum.golang.org
ARG MINIO_SOURCE_SHA256
ARG MINIO_COMMIT
ARG MINIO_RELEASE
ARG MINIO_GO_VERSION
COPY minio-source.tar.gz /tmp/minio-source.tar.gz
RUN printf '%s  /tmp/minio-source.tar.gz\n' "$MINIO_SOURCE_SHA256" | sha256sum -c - \
    && tar -xzf /tmp/minio-source.tar.gz --strip-components=1 \
    && test "$(go env GOVERSION)" = "$MINIO_GO_VERSION" \
    && sha256sum go.mod go.sum > /tmp/minio-module-locks.sha256 \
    && go mod download \
    && go mod verify \
    && sha256sum -c /tmp/minio-module-locks.sha256
RUN go build -p 2 -mod=readonly -trimpath -buildvcs=false -tags kqueue \
    -ldflags "-s -w -X github.com/minio/minio/cmd.Version=2025-09-07T16:13:09Z -X github.com/minio/minio/cmd.ReleaseTag=${MINIO_RELEASE} -X github.com/minio/minio/cmd.CommitID=${MINIO_COMMIT} -X github.com/minio/minio/cmd.ShortCommitID=07c3a429bfed -X github.com/minio/minio/cmd.CopyrightYear=2025" \
    -o /out/minio . \
    && sha256sum -c /tmp/minio-module-locks.sha256

FROM scratch
COPY --from=build /out/minio /minio
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=build /src/LICENSE /usr/share/licenses/minio/LICENSE
LABEL org.opencontainers.image.source="https://github.com/minio/minio" \
      org.opencontainers.image.revision="07c3a429bfed433e49018cb0f78a52145d4bedeb" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.reconforge.fixture.scope="synthetic-disposable-ci-only" \
      org.reconforge.fixture.upstream-status="archived-unmaintained"
ENV HOME=/tmp USER=minio LOGNAME=minio MINIO_BROWSER=off MINIO_UPDATE=off
USER 65532:65532
ENTRYPOINT ["/minio"]
CMD ["server", "/data"]
