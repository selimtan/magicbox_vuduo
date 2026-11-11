/* Internal drawing helpers; no additional Python/SWIG interface. */
#ifndef ENIGMA_GUI_EMAGICBOXDRAWING_H
#define ENIGMA_GUI_EMAGICBOXDRAWING_H
#include <algorithm>
#include <cstdint>

class gPixmap;
class gPainter;
class eSize;

namespace MagicBoxDrawing {
// Integrate the source pixel footprint, weighting RGB by alpha to avoid halos.
// Input/output use the native BGRA surface layout with ordinary opacity alpha.
inline void resizeArea(const uint8_t *src, int iw, int ih, int istride,
	uint8_t *dst, int ow, int oh, int ostride)
{
	const uint64_t total = uint64_t(iw) * ih;
	for (int y = 0; y < oh; ++y) {
		const int top = y * ih, bottom = (y + 1) * ih;
		for (int x = 0; x < ow; ++x) {
			const int left = x * iw, right = (x + 1) * iw;
			uint64_t alpha = 0, color[3] = {};
			for (int sy = top / oh; sy < (bottom + oh - 1) / oh; ++sy) {
				const int wy = std::min(bottom, (sy + 1) * oh) - std::max(top, sy * oh);
				for (int sx = left / ow; sx < (right + ow - 1) / ow; ++sx) {
					const int wx = std::min(right, (sx + 1) * ow) - std::max(left, sx * ow);
					const uint8_t *pixel = src + sy * istride + sx * 4;
					const uint64_t weight = uint64_t(wx) * wy * pixel[3];
					alpha += weight;
					for (int c = 0; c < 3; ++c) color[c] += weight * pixel[c];
				}
			}
			uint8_t *pixel = dst + y * ostride + x * 4;
			for (int c = 0; c < 3; ++c) pixel[c] = alpha ? (color[c] + alpha / 2) / alpha : 0;
			pixel[3] = (alpha + total / 2) / total;
		}
	}
}

gPixmap *smoothPixmap(gPixmap *source, const eSize &target);
void selectedTab(gPainter &painter, int x, int logicalWidth, int canvasWidth, int canvasHeight);
}
#endif
