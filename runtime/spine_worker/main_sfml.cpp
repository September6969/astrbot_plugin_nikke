// SPDX-License-Identifier: GPL-3.0-or-later
// 该文件只提供受限的离线/服务端 Spine 渲染 worker，不包含 Spine 源码。

#include <SFML/Graphics.hpp>
#include <spine/SkeletonBinary.h>
#include <spine/SkeletonJson.h>
#include <spine/spine-sfml.h>

#if defined(__has_include)
#if __has_include(<spine/Version.h>)
#include <spine/Version.h>
#endif
#endif

#include <algorithm>
#include <cerrno>
#include <cmath>
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <iterator>
#include <memory>
#include <string>
#include <vector>

namespace {

inline void *get_page_texture(const spine::AtlasPage *page) {
#if defined(SPINE_MAJOR_VERSION) && (SPINE_MAJOR_VERSION > 4 || (SPINE_MAJOR_VERSION == 4 && SPINE_MINOR_VERSION >= 1))
	return page != nullptr ? page->texture : nullptr;
#else
	return page != nullptr ? page->getRendererObject() : nullptr;
#endif
}

struct Options {
	std::string skeleton;
	std::string atlas;
	std::string output;
	std::string animation = "setup";
	std::string skin;
	int width = 1024;
	int height = 1024;
	float frame_seconds = 0.0f;
	float padding = 0.08f;
	bool verbose = false;
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
			if (!next_value(argc, argv, index, value) || !parse_float(value.c_str(), options.frame_seconds, 0.0f, 60.0f)) return false;
		} else if (std::string(argv[index]) == "--padding") {
			if (!next_value(argc, argv, index, value) || !parse_float(value.c_str(), options.padding, 0.0f, 0.45f)) return false;
		} else if (std::string(argv[index]) == "--verbose") {
			options.verbose = true;
		} else {
			return false;
		}
	}
	return !options.skeleton.empty() && !options.atlas.empty() && !options.output.empty() && !options.animation.empty();
}

bool write_rgba(const std::string &path, int width, int height, const sf::Uint8 *pixels) {
	std::ofstream output(path, std::ios::binary | std::ios::trunc);
	if (!output) return false;
	const std::uint32_t w = static_cast<std::uint32_t>(width);
	const std::uint32_t h = static_cast<std::uint32_t>(height);
	output.write(reinterpret_cast<const char *>(&w), sizeof(w));
	output.write(reinterpret_cast<const char *>(&h), sizeof(h));
	output.write(reinterpret_cast<const char *>(pixels), static_cast<std::streamsize>(width) * height * 4);
	return output.good();
}

bool normalize_atlas_bom(const std::string &path, std::string &temporary_path) {
	std::ifstream input(path, std::ios::binary);
	if (!input) return false;
	const std::string bytes((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
	if (bytes.size() < 3 || static_cast<unsigned char>(bytes[0]) != 0xEF
		|| static_cast<unsigned char>(bytes[1]) != 0xBB || static_cast<unsigned char>(bytes[2]) != 0xBF) {
		return true;
	}
	temporary_path = path + ".utf8";
	std::ofstream output(temporary_path, std::ios::binary | std::ios::trunc);
	if (!output) {
		temporary_path.clear();
		return false;
	}
	output.write(bytes.data() + 3, static_cast<std::streamsize>(bytes.size() - 3));
	if (!output.good()) {
		output.close();
		std::remove(temporary_path.c_str());
		temporary_path.clear();
		return false;
	}
	return true;
}

int render(const Options &options) {
	int result = 1;
	const auto phase = [&options](const char *name) {
		if (options.verbose) {
			std::cerr << "nikke-spine-worker: " << name << "\n";
			std::cerr.flush();
		}
	};
	std::string temporary_atlas;
	phase("开始读取 atlas");
	const bool atlas_ready = normalize_atlas_bom(options.atlas, temporary_atlas);
	const std::string atlas_path = temporary_atlas.empty() ? options.atlas : temporary_atlas;
	{
		spine::SFMLTextureLoader texture_loader;
		phase("开始解析 atlas 与纹理");
		spine::Atlas atlas(atlas_ready ? atlas_path.c_str() : "", &texture_loader);
		if (!atlas_ready) {
			print_error("atlas 文件读取失败");
		} else if (atlas.getPages().size() == 0 || get_page_texture(atlas.getPages()[0]) == nullptr) {
			print_error("atlas 纹理页加载失败");
		} else {
			spine::SkeletonData *skeleton_data = nullptr;
			phase("开始解析 skeleton");
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
				// 数据必须比 drawable 活得更久，避免析构时访问已释放的骨骼定义。
				std::unique_ptr<spine::SkeletonData> owned_data(skeleton_data);
				phase("skeleton 解析完成");
				spine::SkeletonDrawable drawable(skeleton_data);
				drawable.setUsePremultipliedAlpha(true);
				if (options.verbose) {
					std::cerr << "nikke-spine-worker: skins=" << skeleton_data->getSkins().size() << "\n";
					for (size_t skin_index = 0; skin_index < skeleton_data->getSkins().size(); ++skin_index) {
						std::cerr << "nikke-spine-worker: skin[" << skin_index << "]="
								<< skeleton_data->getSkins()[skin_index]->getName().buffer() << "\n";
					}
					std::cerr.flush();
				}
				if (!options.skin.empty() && skeleton_data->findSkin(options.skin.c_str()) == nullptr) {
					print_error("请求的 skin 不存在");
				} else if (options.animation != "setup" && skeleton_data->findAnimation(options.animation.c_str()) == nullptr) {
					print_error("请求的 animation 不存在");
				} else {
					if (!options.skin.empty()) drawable.skeleton->setSkin(options.skin.c_str());
					else if (skeleton_data->getSkins().size() == 1) {
						drawable.skeleton->setSkin(skeleton_data->getSkins()[0]->getName().buffer());
					}
					drawable.skeleton->setToSetupPose();
					drawable.skeleton->setSlotsToSetupPose();
					if (options.animation != "setup") {
						drawable.state->setAnimation(0, options.animation.c_str(), false);
					}
					drawable.update(options.frame_seconds);

					float bounds_x = 0.0f;
					float bounds_y = 0.0f;
					float bounds_width = 0.0f;
					float bounds_height = 0.0f;
					spine::Vector<float> vertices;
					drawable.skeleton->getBounds(bounds_x, bounds_y, bounds_width, bounds_height, vertices);
					const float usable_width = static_cast<float>(options.width) * (1.0f - 2.0f * options.padding);
					const float usable_height = static_cast<float>(options.height) * (1.0f - 2.0f * options.padding);
					if (!std::isfinite(bounds_x) || !std::isfinite(bounds_y)
						|| !std::isfinite(bounds_width) || !std::isfinite(bounds_height)
						|| bounds_width <= 0.0f || bounds_height <= 0.0f || usable_width <= 0.0f || usable_height <= 0.0f) {
						print_error("skeleton bounds 无效");
					} else {
						const float scale = std::min(usable_width / bounds_width, usable_height / bounds_height);
						drawable.skeleton->setScaleX(scale);
						drawable.skeleton->setScaleY(scale);
						// 缩放后先刷新世界坐标，避免用旧边界将人物移出画布。
						drawable.skeleton->updateWorldTransform();
						drawable.skeleton->getBounds(bounds_x, bounds_y, bounds_width, bounds_height, vertices);
						drawable.skeleton->setPosition((static_cast<float>(options.width) - bounds_width) / 2.0f - bounds_x,
											(static_cast<float>(options.height) - bounds_height) / 2.0f - bounds_y);
						drawable.skeleton->updateWorldTransform();

						sf::RenderTexture target;
						if (!target.create(static_cast<unsigned int>(options.width), static_cast<unsigned int>(options.height))) {
							print_error("SFML 输出纹理创建失败");
						} else {
							phase("开始绘制 RenderTexture");
							target.clear(sf::Color(0, 0, 0, 0));
							target.draw(drawable);
							target.display();
							phase("RenderTexture 绘制完成");
							sf::Image image = target.getTexture().copyToImage();
							if (!write_rgba(options.output, options.width, options.height, image.getPixelsPtr())) {
								print_error("RGBA 输出文件写入失败");
							} else {
								std::cout << "{\"status\":\"ok\",\"width\":" << options.width
										  << ",\"height\":" << options.height << "}\n";
								result = 0;
							}
						}
					}
				}
			}
		}
	}
	if (!temporary_atlas.empty()) std::remove(temporary_atlas.c_str());
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
