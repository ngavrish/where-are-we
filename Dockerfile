# A map without installing anything:
#   docker run --rm -v "$PWD:/work" -v "$PWD/.wawe:/out" ghcr.io/ngavrish/where-are-we --repo /work --out /out
FROM python:3.12-alpine
RUN apk add --no-cache git
COPY . /src
RUN pip install --no-cache-dir /src && rm -rf /src
WORKDIR /work
ENTRYPOINT ["where-are-we"]
CMD ["--repo", "/work", "--out", "/out"]
