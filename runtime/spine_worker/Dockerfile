# 只在部署方接受 Spine/SFML 许可和测试素材边界后构建；仓库不分发 runtime。
FROM ubuntu:24.04 AS build

ARG SPINE_COMMIT=425ce416bb218b28caeec47b317aa57cd7140375
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git cmake ninja-build g++ pkg-config wget \
        libfreetype-dev libx11-dev libxrandr-dev libxcursor-dev libxi-dev libgl-dev libudev-dev libopenal-dev libvorbis-dev libogg-dev \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch 4.0 https://github.com/EsotericSoftware/spine-runtimes.git /opt/spine-runtimes \
    && cd /opt/spine-runtimes \
    && git fetch --depth 1 origin "${SPINE_COMMIT}" \
    && git checkout --detach "${SPINE_COMMIT}" \
    && wget --quiet --timeout=30 --tries=5 --waitretry=5 \
        https://github.com/SFML/SFML/releases/download/2.5.1/SFML-2.5.1-linux-gcc-64-bit.tar.gz -O /tmp/sfml.tar.gz \
    && tar -xzf /tmp/sfml.tar.gz -C /opt

COPY CMakeLists.txt /opt/nikke-worker/CMakeLists.txt
COPY main.cpp /opt/nikke-worker/main.cpp
COPY main_sfml.cpp /opt/nikke-worker/main_sfml.cpp
RUN cmake -S /opt/nikke-worker -B /opt/nikke-worker/build -G Ninja -DCMAKE_BUILD_TYPE=Release \
        -DSPINE_ROOT=/opt/spine-runtimes -DSFML_ROOT=/opt/SFML-2.5.1 \
    && cmake --build /opt/nikke-worker/build --target nikke-spine-worker --parallel 2

FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends libfreetype6 libx11-6 libxrandr2 libxcursor1 libxi6 libgl1 libudev1 libflac12 libvorbis0a libvorbisenc2 libogg0 libopenal1 xvfb xauth \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /opt/nikke-worker/build/nikke-spine-worker /usr/local/bin/nikke-spine-worker
COPY --from=build /opt/SFML-2.5.1/lib/ /usr/local/lib/
RUN ldconfig
COPY entrypoint-xvfb.sh /usr/local/bin/entrypoint-xvfb.sh
RUN chmod 0755 /usr/local/bin/entrypoint-xvfb.sh
ENTRYPOINT ["/usr/local/bin/entrypoint-xvfb.sh"]
