/* Grid maze router core for route_pcb.py.
 *
 * The board is sampled on a square grid (plane mm, +Y = back). For every copper layer each cell keeps the
 * clearance-adjusted signed distance to the nearest copper (d1, owned by net n1) and to the nearest copper of
 * any other net (d2). A track of net N with half-width h may run through a cell when
 *     free(N) = (n1 == N ? d2 : d1) >= h + slack,
 * where slack covers the stretch of a step between two cell centres. Holes, SMD pads (for via placement),
 * via keep-outs and a soft cost map are separate single-purpose fields.
 *
 * Search is A* over (layer, cell, heading). Headings make turns cost something and forbid acute corners, so
 * routes come out as straight runs joined by 45 degree bends.
 */
#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define NET_BLOCK 65535
#define FAR 1e9f
#define MAXL 4

typedef struct {
    int nx, ny, nl;
    double x0, y0, res;
    float *d1, *d2;          /* nl * ny * nx */
    uint16_t *n1;            /* nl * ny * nx */
    float *hole;             /* ny * nx: signed distance to the nearest drilled hole edge, any net */
    float *smd;              /* ny * nx: signed distance to the nearest outer-layer SMD pad, any net */
    uint8_t *viablock;       /* ny * nx: 1 = no via centre here */
    uint8_t *cost;           /* nl * ny * nx: soft cost, 16 = one extra step length */
} Grid;

/* ------------------------------------------------------------------ shapes
 * Shape records in a flat double array:
 *   0 capsule:  type, layermask, ax, ay, bx, by, r
 *   1 polygon:  type, layermask, n, x0, y0, ..., x(n-1), y(n-1)      (one ring)
 *   2 board:    type, layermask, rings, n0, pts..., n1, pts...         (outline + cut-outs, even-odd inside)
 */
typedef struct {
    int type, mask, n, rings;
    const double *p;
    double bx0, by0, bx1, by1;   /* bounding box */
} Shape;

static double seg_dist(double px, double py, double ax, double ay, double bx, double by) {
    double dx = bx - ax, dy = by - ay, l2 = dx * dx + dy * dy, t = 0;
    if (l2 > 0) {
        t = ((px - ax) * dx + (py - ay) * dy) / l2;
        if (t < 0) t = 0;
        if (t > 1) t = 1;
    }
    double qx = ax + t * dx - px, qy = ay + t * dy - py;
    return sqrt(qx * qx + qy * qy);
}

/* signed distance of a ring set: negative inside (even-odd) */
static double rings_sdf(double px, double py, const double *p, int rings) {
    double best = 1e18;
    int inside = 0;
    for (int r = 0; r < rings; r++) {
        int n = (int)p[0];
        const double *v = p + 1;
        for (int i = 0, j = n - 1; i < n; j = i++) {
            double xi = v[2 * i], yi = v[2 * i + 1], xj = v[2 * j], yj = v[2 * j + 1];
            if (((yi > py) != (yj > py)) && (px < (xj - xi) * (py - yi) / (yj - yi) + xi)) inside = !inside;
            double d = seg_dist(px, py, xi, yi, xj, yj);
            if (d < best) best = d;
        }
        p += 1 + 2 * n;
    }
    return inside ? -best : best;
}

static double shape_sdf(const Shape *s, double px, double py) {
    if (s->type == 0) return seg_dist(px, py, s->p[0], s->p[1], s->p[2], s->p[3]) - s->p[4];
    if (s->type == 1) {
        double tmp_sdf;
        /* one ring stored as n, pts: reuse rings_sdf with a pointer to the count */
        tmp_sdf = rings_sdf(px, py, s->p - 1, 1);
        return tmp_sdf;
    }
    return rings_sdf(px, py, s->p, s->rings);
}

/* parse one record at rec, return its length in doubles */
static int parse_shape(const double *rec, Shape *s) {
    s->type = (int)rec[0];
    s->mask = (int)rec[1];
    if (s->type == 0) {
        s->p = rec + 2;
        double r = s->p[4];
        s->bx0 = fmin(s->p[0], s->p[2]) - r; s->bx1 = fmax(s->p[0], s->p[2]) + r;
        s->by0 = fmin(s->p[1], s->p[3]) - r; s->by1 = fmax(s->p[1], s->p[3]) + r;
        return 7;
    }
    if (s->type == 1) {
        s->n = (int)rec[2];
        s->p = rec + 3;
        s->bx0 = s->by0 = 1e18; s->bx1 = s->by1 = -1e18;
        for (int i = 0; i < s->n; i++) {
            s->bx0 = fmin(s->bx0, s->p[2 * i]); s->bx1 = fmax(s->bx1, s->p[2 * i]);
            s->by0 = fmin(s->by0, s->p[2 * i + 1]); s->by1 = fmax(s->by1, s->p[2 * i + 1]);
        }
        return 3 + 2 * s->n;
    }
    s->rings = (int)rec[2];
    s->p = rec + 3;
    s->bx0 = s->by0 = 1e18; s->bx1 = s->by1 = -1e18;
    const double *q = s->p;
    int len = 3;
    for (int r = 0; r < s->rings; r++) {
        int n = (int)q[0];
        for (int i = 0; i < n; i++) {
            s->bx0 = fmin(s->bx0, q[1 + 2 * i]); s->bx1 = fmax(s->bx1, q[1 + 2 * i]);
            s->by0 = fmin(s->by0, q[2 + 2 * i]); s->by1 = fmax(s->by1, q[2 + 2 * i]);
        }
        q += 1 + 2 * n;
        len += 1 + 2 * n;
    }
    return len;
}

static inline int clampi(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }

/* ------------------------------------------------------------------ stamping
 * kind 0: copper on each layer in the shape's mask, value = sdf - clearance, owned by net
 * kind 1: hole field (min of sdf)        kind 2: smd field (min of sdf)
 * kind 3: via block where sdf < clearance          kind 4: cost += value where sdf < clearance
 * invert: use -sdf (board outline: outside is copper-free space we must stay away from)
 * whole: visit every cell (needed when invert, since everything outside the board must be marked)
 */
void stamp(Grid *g, const double *rec, int kind, double clearance, int net, double reach, int invert, int value) {
    Shape s;
    parse_shape(rec, &s);
    int ix0, iy0, ix1, iy1;
    if (invert) {
        ix0 = 0; iy0 = 0; ix1 = g->nx - 1; iy1 = g->ny - 1;
    } else {
        double m = clearance + reach;
        ix0 = clampi((int)floor((s.bx0 - m - g->x0) / g->res), 0, g->nx - 1);
        ix1 = clampi((int)ceil((s.bx1 + m - g->x0) / g->res), 0, g->nx - 1);
        iy0 = clampi((int)floor((s.by0 - m - g->y0) / g->res), 0, g->ny - 1);
        iy1 = clampi((int)ceil((s.by1 + m - g->y0) / g->res), 0, g->ny - 1);
    }
    size_t plane = (size_t)g->nx * g->ny;
    for (int iy = iy0; iy <= iy1; iy++) {
        double py = g->y0 + iy * g->res;
        for (int ix = ix0; ix <= ix1; ix++) {
            double px = g->x0 + ix * g->res;
            double d = shape_sdf(&s, px, py);
            if (invert) d = -d;
            size_t c = (size_t)iy * g->nx + ix;
            if (kind == 0) {
                float v = (float)(d - clearance);
                if (!invert && v > reach) continue;
                for (int l = 0; l < g->nl; l++) {
                    if (!(s.mask & (1 << l))) continue;
                    size_t k = l * plane + c;
                    if (g->n1[k] == net) {
                        if (v < g->d1[k]) g->d1[k] = v;
                    } else if (v < g->d1[k]) {
                        g->d2[k] = g->d1[k];
                        g->d1[k] = v;
                        g->n1[k] = (uint16_t)net;
                    } else if (v < g->d2[k]) {
                        g->d2[k] = v;
                    }
                }
            } else if (kind == 1) {
                if ((float)d < g->hole[c]) g->hole[c] = (float)d;
            } else if (kind == 2) {
                if ((float)d < g->smd[c]) g->smd[c] = (float)d;
            } else if (kind == 3) {
                if (d < clearance) g->viablock[c] = 1;
            } else if (kind == 4) {
                if (d < clearance)
                    for (int l = 0; l < g->nl; l++)
                        if (s.mask & (1 << l)) {
                            size_t k = l * plane + c;
                            int v = g->cost[k] + value;
                            g->cost[k] = (uint8_t)(v > 255 ? 255 : v);
                        }
            }
        }
    }
}

void reset(Grid *g) {
    size_t n = (size_t)g->nl * g->nx * g->ny, m = (size_t)g->nx * g->ny;
    for (size_t i = 0; i < n; i++) { g->d1[i] = FAR; g->d2[i] = FAR; g->n1[i] = 0; g->cost[i] = 0; }
    for (size_t i = 0; i < m; i++) { g->hole[i] = FAR; g->smd[i] = FAR; g->viablock[i] = 0; }
}

static inline float free_for(const Grid *g, size_t k, int net) { return g->n1[k] == net ? g->d2[k] : g->d1[k]; }

/* ------------------------------------------------------------------ search */
typedef struct {
    int net;
    int layers;                 /* routing layers bitmask */
    float hw[MAXL], hwn[MAXL];  /* free() needed for a wide / narrowed track on each layer */
    float via_r, via_hole, via_smd, via_cost;
    int allow_via;
    float layer_cost[MAXL];
    float turn45, turn90, narrow_pen, cost_scale;
    int wx0, wy0, wx1, wy1;     /* search window, cells, inclusive */
    int target_via;             /* 1: a cell that can take a via is a goal too (besides the target shapes) */
    int vx0, vy0, vx1, vy1;     /* allowed via cells when target_via */
    long max_expand;
    float conflict_cost;        /* with a conflict grid: extra cost per step that would hit its copper */
} Params;

static const int DX[8] = {1, 1, 0, -1, -1, -1, 0, 1};
static const int DY[8] = {0, 1, 1, 1, 0, -1, -1, -1};

typedef struct { float f; int32_t s; } HeapItem;
typedef struct { HeapItem *a; int n, cap; } Heap;

static void hpush(Heap *h, float f, int32_t s) {
    if (h->n == h->cap) { h->cap = h->cap ? h->cap * 2 : 4096; h->a = realloc(h->a, h->cap * sizeof(HeapItem)); }
    int i = h->n++;
    while (i > 0) {
        int p = (i - 1) / 2;
        if (h->a[p].f <= f) break;
        h->a[i] = h->a[p];
        i = p;
    }
    h->a[i].f = f; h->a[i].s = s;
}

static HeapItem hpop(Heap *h) {
    HeapItem top = h->a[0], last = h->a[--h->n];
    int i = 0;
    for (;;) {
        int l = 2 * i + 1, r = l + 1, m = i;
        float fm = last.f;
        if (l < h->n && h->a[l].f < fm) { m = l; fm = h->a[l].f; }
        if (r < h->n && h->a[r].f < fm) { m = r; }
        if (m == i) break;
        h->a[i] = h->a[m];
        i = m;
    }
    if (h->n) h->a[i] = last;
    return top;
}

int via_fits(const Grid *g, const Params *p, int ix, int iy) {
    size_t c = (size_t)iy * g->nx + ix, plane = (size_t)g->nx * g->ny;
    if (g->viablock[c] || g->hole[c] < p->via_hole || g->smd[c] < p->via_smd) return 0;
    for (int l = 0; l < g->nl; l++)
        if (free_for(g, l * plane + c, p->net) < p->via_r) return 0;
    return 1;
}

/* rasterise a shape list into a window bitmask (bit per layer) */
static void raster(const Grid *g, const Params *p, const double *shapes, int nshapes, uint8_t *mask,
                   int W, int H, int *rects, int *nrects) {
    const double *rec = shapes;
    for (int i = 0; i < nshapes; i++) {
        Shape s;
        rec += parse_shape(rec, &s);
        int ix0 = clampi((int)floor((s.bx0 - g->x0) / g->res), p->wx0, p->wx1);
        int ix1 = clampi((int)ceil((s.bx1 - g->x0) / g->res), p->wx0, p->wx1);
        int iy0 = clampi((int)floor((s.by0 - g->y0) / g->res), p->wy0, p->wy1);
        int iy1 = clampi((int)ceil((s.by1 - g->y0) / g->res), p->wy0, p->wy1);
        int hit = 0;
        for (int iy = iy0; iy <= iy1; iy++)
            for (int ix = ix0; ix <= ix1; ix++)
                if (shape_sdf(&s, g->x0 + ix * g->res, g->y0 + iy * g->res) <= 1e-9) {
                    mask[(iy - p->wy0) * W + (ix - p->wx0)] |= (uint8_t)s.mask;
                    hit = 1;
                }
        if (rects && hit) {
            int *r = rects + 4 * (*nrects)++;
            r[0] = ix0; r[1] = iy0; r[2] = ix1; r[3] = iy1;
        }
    }
    (void)H;
}

/* Returns path length (cells) written to out as (layer, ix, iy, flags) quads; flags: 1 = the step into this cell is
 * narrowed, 2 = via here (layer changes after this cell). -1 = no route, -2 = expansion cap hit. */
int astar(const Grid *g, const Params *p, const double *src, int nsrc, const double *tgt, int ntgt,
          const double *narrow, int nnarrow, int32_t *out, int outcap, const Grid *cg) {
    /* cg (may be NULL): the full board. g then holds only what must never be crossed, and every step that would
     * hit cg's copper costs conflict_cost, so the path found disturbs as little routed copper as possible. */
    int W = p->wx1 - p->wx0 + 1, H = p->wy1 - p->wy0 + 1;
    size_t WH = (size_t)W * H, plane = (size_t)g->nx * g->ny;
    int lmap[MAXL], lrev[MAXL], NL = 0;
    for (int l = 0; l < g->nl; l++) {
        lmap[l] = -1;
        if (p->layers & (1 << l)) { lmap[l] = NL; lrev[NL++] = l; }
    }
    size_t NS = WH * NL * 9;
    float *gs = malloc(NS * sizeof(float));
    int32_t *par = malloc(NS * sizeof(int32_t));
    uint8_t *closed = calloc(NS, 1), *nar = calloc(NS, 1);
    uint8_t *smask = calloc(WH, 1), *tmask = calloc(WH, 1), *nmask = calloc(WH, 1);
    int *rects = malloc(sizeof(int) * 4 * (ntgt + 1));
    int nrects = 0;
    for (size_t i = 0; i < NS; i++) gs[i] = FAR;
    raster(g, p, src, nsrc, smask, W, H, NULL, NULL);
    raster(g, p, tgt, ntgt, tmask, W, H, rects, &nrects);
    raster(g, p, narrow, nnarrow, nmask, W, H, NULL, NULL);
    float lmin = FAR;
    for (int i = 0; i < NL; i++) if (p->layer_cost[lrev[i]] < lmin) lmin = p->layer_cost[lrev[i]];

#define STATE(li, x, y, d) ((int32_t)((((size_t)(li) * H + (y)) * W + (x)) * 9 + (d)))
    Heap h = {0};
    int result = -1;
    int32_t goal = -1;

    for (int y = 0; y < H; y++)
        for (int x = 0; x < W; x++) {
            uint8_t m = smask[y * W + x];
            if (!m) continue;
            size_t c = (size_t)(y + p->wy0) * g->nx + (x + p->wx0);
            for (int li = 0; li < NL; li++) {
                int l = lrev[li];
                if (!(m & (1 << l))) continue;
                float fr = free_for(g, l * plane + c, p->net);
                if (fr < p->hwn[l]) continue;
                int32_t s = STATE(li, x, y, 8);
                gs[s] = 0;
                par[s] = -1;
                hpush(&h, 0, s);
            }
        }

    long expanded = 0;
    while (h.n) {
        HeapItem it = hpop(&h);
        int32_t s = it.s;
        if (closed[s]) continue;
        closed[s] = 1;
        if (++expanded > p->max_expand) { result = -2; break; }
        int d = s % 9, rest = s / 9;
        int x = rest % W, y = (rest / W) % H, li = rest / (W * H);
        int l = lrev[li];
        int gx = x + p->wx0, gy = y + p->wy0;
        size_t c = (size_t)gy * g->nx + gx;
        float gc = gs[s];
        if (tmask[y * W + x] & (1 << l)) {
            goal = s; result = 0; break;
        }
        if (p->target_via && gx >= p->vx0 && gx <= p->vx1 && gy >= p->vy0 && gy <= p->vy1 && via_fits(g, p, gx, gy)) {
            goal = s; result = 0; break;
        }
        /* planar moves */
        for (int nd = 0; nd < 8; nd++) {
            float turn = 0;
            if (d != 8) {
                int a = abs(nd - d); if (a > 4) a = 8 - a;
                if (a >= 3) continue;
                turn = a == 1 ? p->turn45 : (a == 2 ? p->turn90 : 0);
            }
            int nx = x + DX[nd], ny = y + DY[nd];
            if (nx < 0 || ny < 0 || nx >= W || ny >= H) continue;
            size_t nc = (size_t)(ny + p->wy0) * g->nx + (nx + p->wx0);
            size_t k = l * plane + nc;
            /* Every point of a step lies within res/2 (straight) or res/sqrt2 (diagonal) of one of its two cell
             * centres, and free() is 1-Lipschitz, so both ends clearing half-width + that margin clears the step.
             * hw/hwn hold half-width + res/2; diagonal steps add the rest. */
            float diag = (nd & 1) ? (float)(g->res * 0.20710678) : 0.0f;
            float fr = free_for(g, k, p->net), fa = free_for(g, l * plane + c, p->net);
            if (fa < fr) fr = fa;
            float step = (nd & 1) ? 1.41421356f : 1.0f;
            float extra = 0;
            int narrowed = 0;
            if (fr < p->hw[l] + diag) {
                if (fr < p->hwn[l] + diag || !(nmask[ny * W + nx] & (1 << l))) continue;
                extra = p->narrow_pen;
                narrowed = 1;
            }
            float cost = step * p->layer_cost[l] * (1.0f + g->cost[k] * p->cost_scale / 16.0f) + turn + extra;
            if (cg && free_for(cg, k, p->net) < (narrowed ? p->hwn[l] : p->hw[l]) + diag) cost += p->conflict_cost;
            int32_t ns = STATE(li, nx, ny, nd);
            if (closed[ns]) continue;
            float ng = gc + cost;
            if (ng < gs[ns]) {
                gs[ns] = ng;
                par[ns] = s;
                nar[ns] = (uint8_t)narrowed;
                float hh = 0;
                if (!p->target_via) {
                    hh = FAR;
                    int ax = nx + p->wx0, ay = ny + p->wy0;
                    for (int r = 0; r < nrects; r++) {
                        int *R = rects + 4 * r;
                        int dx = ax < R[0] ? R[0] - ax : (ax > R[2] ? ax - R[2] : 0);
                        int dy = ay < R[1] ? R[1] - ay : (ay > R[3] ? ay - R[3] : 0);
                        int mx = dx > dy ? dx : dy, mn = dx > dy ? dy : dx;
                        float o = (mx + 0.41421356f * mn) * lmin;
                        if (o < hh) hh = o;
                    }
                }
                hpush(&h, ng + hh, ns);
            }
        }
        /* via */
        if (p->allow_via && !p->target_via && NL > 1 && via_fits(g, p, gx, gy)) {
            for (int lj = 0; lj < NL; lj++) {
                if (lj == li) continue;
                int l2 = lrev[lj];
                if (free_for(g, l2 * plane + c, p->net) < p->hwn[l2]) continue;
                int32_t ns = STATE(lj, x, y, 8);
                if (closed[ns]) continue;
                float ng = gc + p->via_cost + (cg && !via_fits(cg, p, gx, gy) ? p->conflict_cost * 4 : 0.0f);
                if (ng < gs[ns]) {
                    gs[ns] = ng;
                    par[ns] = s;
                    nar[ns] = 0;
                    hpush(&h, ng, ns);
                }
            }
        }
    }

    int len = 0;
    if (result == 0) {
        /* walk back */
        int32_t s = goal;
        int prev_li = -1;
        while (s >= 0 && len < outcap) {
            int rest = s / 9;
            int x = rest % W, y = (rest / W) % H, li = rest / (W * H);
            int l = lrev[li];
            int flags = nar[s];      /* the step that arrived here was narrowed */
            if (prev_li >= 0 && prev_li != li) out[4 * (len - 1) + 3] |= 2;
            out[4 * len] = l; out[4 * len + 1] = x + p->wx0; out[4 * len + 2] = y + p->wy0; out[4 * len + 3] = flags;
            len++;
            prev_li = li;
            s = par[s];
        }
        result = len;
    }
    free(gs); free(par); free(closed); free(nar); free(smask); free(tmask); free(nmask); free(rects); free(h.a);
    return result;
#undef STATE
}

/* free() of one cell, for checks from Python */
float cell_free(const Grid *g, int l, int ix, int iy, int net) {
    return free_for(g, (size_t)l * g->nx * g->ny + (size_t)iy * g->nx + ix, net);
}
