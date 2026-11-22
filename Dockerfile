FROM golang:1.26.1-bookworm@sha256:ab3d6955bbc813a0f3fdf220c1d817dd89c0b3f283777db8ece4a32fe7858edd AS build
WORKDIR /src
COPY go.mod ./
COPY mech ./mech
COPY cmd/bot ./cmd/bot
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags="-s -w" -o /mechbot ./cmd/bot

FROM scratch
COPY --from=build /mechbot /mechbot
ARG MECH_TUNE="LowBonus=600"
ENV MECH_TUNE=${MECH_TUNE}
USER 65534:65534
ENTRYPOINT ["/mechbot"]
