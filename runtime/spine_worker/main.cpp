// SPDX-License-Identifier: GPL-3.0-or-later
// 该文件只提供受限的离线/服务端 Spine 渲染 worker，不包含 Spine 源码。

#include <SDL.h>
#include <spine-sdl-cpp.h>
#include <spine/SkeletonBinary.h>
#include <spine/SkeletonJson.h>

#include <algorithm>
#include <cerrno>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

namespace {

struct Options {
	std::string skeleton;
	std::string atlas;
	std::string output;
	std::string animation = "aim";
	std::string skin;
	int width = 1024;
	int height = 1024;
	float frame_seconds = 0.0f;
	float padding = 0.08f;
};

void print_error(const std::string &message) {
	std::cerr << "nikke-spine-worker: " << message << "\n";
}

bool parse_int(const char *value, int &out) {
	char *end = nullptr;
	errno = 0;
	long parsed = std::strtol(value, &end, 10);
	if (errno != 0 || end == value || *end != '\0' || parsed < 1 || parsed > 4096) return false;
	out = static_cast<int>(parsed);
	return true;
}

bool parse_float(const char *value, float &out, float minimum, float maximum) {
	char *end = nullptr;
	errno = 0;
	float parsed = std::strtof(value, &end);
	if (errno != 0 || end == value || *end != '\0' || !std::isfinite(parsed) || parsed < minimum || parsed > maximum) {
		return false;
	}
	out = parsed;
	return true;
}

bool next_value(int argc, char **argv, int &index, std::string &value) {
	if (index + 1 >= argc) return false;
	value = argv[++index];
	return !value.empty();
}

bool parse_args(int argc, char **argv, Options &options) {
	for (int index = 1; index < argc; ++index) {
		std::string value;
		if (std::string(argv[index]) == "--skeleton") {
			if (!next_value(argc, argv, index, options.skeleton)) return false;
		} else if (std::string(argv[index]) == "--atlas") {
			if (!next_value(argc, argv, index, options.atlas)) return false;
		} else if (std::string(argv[index]) == "--output") {
			if (!next_value(argc, argv, index, options.output)) return false;
		} else if (std::string(argv[index]) == "--animation") {
			if (!next_value(argc, argv, index, options.animation)) return false;
		} else if (std::string(argv[index]) == "--skin") {
			if (!next_value(argc, argv, index, options.skin)) return false;
		} else if (std::string(argv[index]) == "--width") {
			if (!next_value(argc, argv, index, value) || !parse_int(value.c_str(), options.width)) return false;
		} else if (std::string(argv[index]) == "--height") {
			if (!next_value(argc, argv, index, value) || !parse_int(value.c_str(), options.height)) return false;
		} else if (std::string(argv[index]) == "--frame-seconds") {
			if (!next_value(argc, argv, index, value) || !parse_float(value.c_str(), options.frame_seconds, 0.0f, 60.0f)) {
				return false;
			}
		} else if (std::string(argv[index]) == "--padding") {
			if (!next_value(argc, argv, index, value) || !parse_float(value.c_str(), options.padding, 0.0f, 0.45f)) {
				return false;
			}
		} else {
			return false;
		}
	}
	return !options.skeleton.empty() && !options.atlas.empty() && !options.output.empty() && !options.animation.empty();
}

bool write_rgba(const std::string &path, int width, int height, const std::uint8_t *pixels) {
	std::ofstream output(path, std::ios::binary | std::ios::trunc);
	if (!output) return false;
	const std::uint32_t w = static_cast<std::uint32_t>(width);
	const std::uint32_t h = static_cast<std::uint32_t>(height);
	output.write(reinterpret_cast<const char *>(&w), sizeof(w));
	output.write(reinterpret_cast<const char *>(&h), sizeof(h));
	output.write(reinterpret_cast<const char *>(pixels), static_cast<std::streamsize>(width) * height * 4);
	return output.good();
}

int render(const Options &options) {
	if (SDL_Init(SDL_INIT_VIDEO) != 0) {
		print_error(std::string("SDL 初始化失败: ") + SDL_GetError());
		return 2;
	}

	SDL_Window *window = SDL_CreateWindow("Nikke Spine Worker", SDL_WINDOWPOS_UNDEFINED, SDL_WINDOWPOS_UNDEFINED, 1, 1, SDL_WINDOW_HIDDEN);
	if (!window) {
		print_error(std::string("SDL 窗口创建失败: ") + SDL_GetError());
		SDL_Quit();
		return 2;
	}
	SDL_Renderer *renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_SOFTWARE | SDL_RENDERER_TARGETTEXTURE);
	if (!renderer) {
		print_error(std::string("SDL 软件 renderer 创建失败: ") + SDL_GetError());
		SDL_DestroyWindow(window);
		SDL_Quit();
		return 2;
	}

	int result = 1;
	{
		spine::SDLTextureLoader texture_loader(renderer);
		spine::Atlas atlas(options.atlas.c_str(), &texture_loader);
		if (atlas.getPages().size() == 0 || atlas.getPages()[0]->texture == nullptr) {
			print_error("atlas 纹理页加载失败");
		} else {
			spine::SkeletonData *skeleton_data = nullptr;
			const bool is_json = options.skeleton.size() >= 5 && options.skeleton.substr(options.skeleton.size() - 5) == ".json";
			if (is_json) {
				spine::SkeletonJson parser(&atlas);
				skeleton_data = parser.readSkeletonDataFile(options.skeleton.c_str());
				if (!skeleton_data) print_error(std::string("JSON skeleton 加载失败: ") + parser.getError().buffer());
			} else {
				spine::SkeletonBinary parser(&atlas);
				skeleton_data = parser.readSkeletonDataFile(options.skeleton.c_str());
				if (!skeleton_data) print_error(std::string("binary skeleton 加载失败: ") + parser.getError().buffer());
			}

			if (skeleton_data) {
				spine::SkeletonDrawable drawable(skeleton_data);
				if (!options.skin.empty() && skeleton_data->findSkin(options.skin.c_str()) == nullptr) {
					print_error("请求的 skin 不存在");
				} else if (skeleton_data->findAnimation(options.animation.c_str()) == nullptr) {
					print_error("请求的 animation 不存在");
				} else {
					if (!options.skin.empty()) drawable.skeleton->setSkin(options.skin.c_str());
					drawable.skeleton->setToSetupPose();
					drawable.skeleton->setSlotsToSetupPose();
					drawable.animationState->setAnimation(0, options.animation.c_str(), false);
					drawable.update(options.frame_seconds);

					float bounds_x = 0.0f;
					float bounds_y = 0.0f;
					float bounds_width = 0.0f;
					float bounds_height = 0.0f;
					spine::Vector<float> vertices;
					drawable.skeleton->getBounds(bounds_x, bounds_y, bounds_width, bounds_height, vertices);
					const float usable_width = static_cast<float>(options.width) * (1.0f - 2.0f * options.padding);
					const float usable_height = static_cast<float>(options.height) * (1.0f - 2.0f * options.padding);
					if (bounds_width <= 0.0f || bounds_height <= 0.0f || usable_width <= 0.0f || usable_height <= 0.0f) {
						print_error("skeleton bounds 无效");
					} else {
						const float scale = std::min(usable_width / bounds_width, usable_height / bounds_height);
						drawable.skeleton->setScale(scale);
						drawable.skeleton->getBounds(bounds_x, bounds_y, bounds_width, bounds_height, vertices);
						drawable.skeleton->setPosition((static_cast<float>(options.width) - bounds_width) / 2.0f - bounds_x,
													(static_cast<float>(options.height) - bounds_height) / 2.0f - bounds_y);
						drawable.skeleton->updateWorldTransform();

						SDL_Texture *target = SDL_CreateTexture(renderer, SDL_PIXELFORMAT_RGBA8888, SDL_TEXTUREACCESS_TARGET, options.width, options.height);
						if (!target) {
							print_error(std::string("输出纹理创建失败: ") + SDL_GetError());
						} else if (SDL_SetRenderTarget(renderer, target) != 0) {
							print_error(std::string("输出纹理绑定失败: ") + SDL_GetError());
						} else {
							SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_BLEND);
							SDL_SetRenderDrawColor(renderer, 0, 0, 0, 0);
							SDL_RenderClear(renderer);
							drawable.draw(renderer);
							std::vector<std::uint8_t> pixels(static_cast<size_t>(options.width) * options.height * 4, 0);
							if (SDL_RenderReadPixels(renderer, nullptr, SDL_PIXELFORMAT_RGBA8888, pixels.data(), options.width * 4) != 0) {
								print_error(std::string("RGBA 读回失败: ") + SDL_GetError());
							} else if (!write_rgba(options.output, options.width, options.height,
										 pixels.data())) {
								print_error("RGBA 输出文件写入失败");
							} else {
								std::cout << "{\"status\":\"ok\",\"width\":" << options.width << ",\"height\":" << options.height << "}\n";
								result = 0;
							}
						}
						SDL_DestroyTexture(target);
					}
				}
				delete skeleton_data;
			}
		}
	}

	SDL_DestroyRenderer(renderer);
	SDL_DestroyWindow(window);
	SDL_Quit();
	return result;
}

} // 匿名命名空间

int main(int argc, char **argv) {
	Options options;
	if (!parse_args(argc, argv, options)) {
		print_error("参数无效");
		return 2;
	}
	return render(options);
}
