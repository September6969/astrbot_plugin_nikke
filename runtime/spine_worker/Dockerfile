# 只在部署方明确接受 Spine 许可与测试素材边界后构建；仓库不分发官方 runtime。
FROM ubuntu:24.04 AS build

ARG SPINE_COMMIT=77a5db0ec6d16331f5efbaa7662bba9355bd3424
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git cmake ninja-build g++ pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch 4.1 https://github.com/EsotericSoftware/spine-runtimes.git /opt/spine-runtimes \
    && cd /opt/spine-runtimes \
    && git fetch --depth 1 origin "${SPINE_COMMIT}" \
    && git checkout --detach "${SPINE_COMMIT}"

COPY CMakeLists.txt /opt/nikke-worker/CMakeLists.txt
COPY main.cpp /opt/nikke-worker/main.cpp
RUN cmake -S /opt/nikke-worker -B /opt/nikke-worker/build -G Ninja -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /opt/nikke-worker/build --target nikke-spine-worker

FROM ubuntu:24.04
ENV SDL_VIDEODRIVER=dummy SDL_RENDER_DRIVER=software
COPY --from=build /opt/nikke-worker/build/nikke-spine-worker /usr/local/bin/nikke-spine-worker
ENTRYPOINT ["/usr/local/bin/nikke-spine-worker"]
