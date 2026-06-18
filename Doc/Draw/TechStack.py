import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch

# === 配置全局中文字体 ===
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False 

# ==========================================
# 1. 全局布局参数化设置 (网格与尺寸)
# ==========================================
fig, ax = plt.subplots(figsize=(18, 12.5))  # 稍微加高画布以容纳新增的头部空间
ax.set_xlim(0, 18)
ax.set_ylim(0, 13)
ax.axis('off')

# 定义标准组件尺寸
W = 2.8   # 宽度
H = 1.3   # 高度

# 定义四列的标准 X 坐标 (网格化布局)
X = [1.0, 4.3, 7.6, 10.9] 

# 定义各层的 Y 基准线坐标 (整体拉开间距)
Y_CLIENT = 9.5
Y_BACK1  = 7.1
Y_BACK2  = 5.2
Y_DATA   = 2.8
Y_EXT    = 0.5

# ==========================================
# 2. 现代柔和配色系统 (基于 Tailwind CSS)
# ==========================================
tw = {
    'blue_bg': '#EFF6FF', 'blue_box': '#DBEAFE', 'blue_border': '#3B82F6', 'blue_text': '#1E3A8A', # 客户端层
    'amber_bg': '#FFFBEB', 'amber_box': '#FEF08A', 'amber_border': '#EAB308', 'amber_text': '#713F12', # 后端层
    'green_bg': '#F0FDF4', 'green_box': '#BBF7D0', 'green_border': '#22C55E', 'green_text': '#14532D', # 数据层
    'slate_bg': '#F8FAFC', 'slate_box': '#E2E8F0', 'slate_border': '#64748B', 'slate_text': '#0F172A', # 外部层
    'pink_box': '#FBCFE8', 'pink_border': '#EC4899', 'pink_text': '#831843', # 特别高亮：计算/算法节点
}

# ==========================================
# 3. 核心绘图辅助函数
# ==========================================
def draw_layer_panel(ax, y, h, title, bg_c, border_c):
    """绘制包裹一整层的背景虚线底板"""
    rect = FancyBboxPatch((0.5, y), 13.6, h, boxstyle="round,pad=0.05,rounding_size=0.15",
                          facecolor=bg_c, edgecolor=border_c, linewidth=1.5, linestyle='--', alpha=0.7, zorder=0)
    ax.add_patch(rect)
    ax.text(13.9, y + h - 0.25, title, fontsize=12, fontweight='bold', color='#1E293B', ha='right', va='center', zorder=2)

def draw_comp(ax, x, y, w, h, title, subtitle, box_c, border_c, text_c):
    """绘制带标题和副标题的精美圆角组件块"""
    box = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.1",
                         facecolor=box_c, edgecolor=border_c, linewidth=1.5, zorder=3)
    ax.add_patch(box)
    ax.text(x + w/2, y + h*0.68, title, fontsize=11, ha='center', va='center', fontweight='bold', color=text_c, zorder=4)
    if subtitle:
        ax.text(x + w/2, y + h*0.28, subtitle, fontsize=9, ha='center', va='center', color='#475569', zorder=4, linespacing=1.4)

def draw_arrow(ax, x1, y1, x2, y2, color='#94A3B8', style='-|>', lw=2.0):
    """绘制带自适应缩进的直线连线箭头"""
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle=style, color=color, lw=lw, shrinkA=4, shrinkB=4))

# 【新增】专门用于绘制拐角避让的连线函数
def draw_elbow_arrow(ax, x1, y1, x2, y2, bend_x, color='#94A3B8', lw=2.0):
    """绘制带直角的避让连线 (左出 -> 向下 -> 左入)"""
    # 绘制从起点到拐角的两段实线 (先向左，再向下)
    ax.plot([x1, bend_x, bend_x], [y1, y1, y2], color=color, lw=lw, zorder=1)
    # 绘制最后一段带有箭头的横线 (向右指回目标框)
    ax.annotate('', xy=(x2, y2), xytext=(bend_x, y2),
                arrowprops=dict(arrowstyle='-|>', color=color, lw=lw, shrinkB=4))

# ==========================================
# 4. 绘制层级背景板
# ==========================================
draw_layer_panel(ax, Y_CLIENT - 0.3, 2.1, '客户端层 (Vue 3 + TypeScript + Vite)', tw['blue_bg'], tw['blue_border'])
draw_layer_panel(ax, Y_BACK2 - 0.3, 4.0, '后端服务层 (FastAPI + Celery + Python)', tw['amber_bg'], tw['amber_border'])
draw_layer_panel(ax, Y_DATA - 0.3, 2.1, '数据存储层', tw['green_bg'], tw['green_border'])
draw_layer_panel(ax, Y_EXT - 0.3, 2.1, '外部数据源', tw['slate_bg'], tw['slate_border'])

# ==========================================
# 5. 绘制核心组件块
# ==========================================
# --- 客户端层 ---
draw_comp(ax, X[0], Y_CLIENT, W, H, '3D地球模式', 'CesiumJS + vue-cesium\n原生Entity / CZML', tw['blue_box'], tw['blue_border'], tw['blue_text'])
draw_comp(ax, X[1], Y_CLIENT, W, H, '平面地图模式', 'MapLibre GL JS\n矢量瓦片 + 3D地形', tw['blue_box'], tw['blue_border'], tw['blue_text'])
draw_comp(ax, X[2], Y_CLIENT, W, H, '共享组件与状态', 'Naive UI + Pinia\n时间轴 / 统一图层控制', tw['blue_box'], tw['blue_border'], tw['blue_text'])
draw_comp(ax, X[3], Y_CLIENT, W, H, '大数据叠加 (仅2D)', 'deck.gl\nGPU百万级点渲染', tw['pink_box'], tw['pink_border'], tw['pink_text']) 

# --- 后端层 (上排: 核心逻辑) ---
draw_comp(ax, X[0], Y_BACK1, W, H, 'API Gateway', 'Nginx\n反向代理 + SSL', tw['amber_box'], tw['amber_border'], tw['amber_text'])
draw_comp(ax, X[1], Y_BACK1, W, H, 'Web 服务', 'FastAPI\n全异步API / 路由分发', tw['amber_box'], tw['amber_border'], tw['amber_text'])
draw_comp(ax, X[2], Y_BACK1, W, H, '异步任务调度', 'Celery + Redis\nFlower后台监控面板', tw['amber_box'], tw['amber_border'], tw['amber_text'])
draw_comp(ax, X[3], Y_BACK1, W, H, '算法执行引擎', 'importlib动态加载\n执行Python模型脚本', tw['pink_box'], tw['pink_border'], tw['pink_text'])

# --- 后端层 (下排: 支撑服务) ---
draw_comp(ax, X[0], Y_BACK2, W, H, 'GEE 代理服务', 'ee Python API\n免下载实时切片代理', tw['amber_box'], tw['amber_border'], tw['amber_text'])
draw_comp(ax, X[1], Y_BACK2, W, H, '瓦片服务引擎', 'Martin (矢量)\nTiTiler (栅格COG)', tw['amber_box'], tw['amber_border'], tw['amber_text'])
draw_comp(ax, X[2], Y_BACK2, W, H, '高速缓存层', 'Redis\n瓦片/计算结果/任务状态', tw['amber_box'], tw['amber_border'], tw['amber_text'])

# --- 数据层 ---
draw_comp(ax, X[0], Y_DATA, W, H, '矢量与业务数据库', 'PostgreSQL + PostGIS\n边界/元数据/用户信息', tw['green_box'], tw['green_border'], tw['green_text'])
draw_comp(ax, X[1], Y_DATA, W, H, '海量栅格存储', 'MinIO (S3兼容)\n长时间序列COG文件', tw['green_box'], tw['green_border'], tw['green_text'])
draw_comp(ax, X[2], Y_DATA, W, H, '计算结果落盘', '本地磁盘/NAS\nGeoTIFF / JSON', tw['green_box'], tw['green_border'], tw['green_text'])
draw_comp(ax, X[3], Y_DATA, W, H, '静态数据集文件夹', '各课题组多源算法数据\n结构化目录管理', tw['pink_box'], tw['pink_border'], tw['pink_text']) 

# --- 外部依赖层 ---
draw_comp(ax, X[0], Y_EXT, W, H, 'Google Earth Engine', '全球尺度遥感数据\n云端计算平台', tw['slate_box'], tw['slate_border'], tw['slate_text'])
draw_comp(ax, X[1], Y_EXT, W, H, '外部公共接口', '国家气象局 / NASA\n实时动态数据获取', tw['slate_box'], tw['slate_border'], tw['slate_text'])
draw_comp(ax, X[2], Y_EXT, W, H, '公共 OGC 服务', 'WMS / WFS / WCS\n外部标准地理服务', tw['slate_box'], tw['slate_border'], tw['slate_text'])

# ==========================================
# 6. 逻辑流向箭头
# ==========================================
draw_arrow(ax, X[0]+W, Y_BACK1+H/2, X[1], Y_BACK1+H/2) 
draw_arrow(ax, X[1]+W, Y_BACK1+H/2, X[2], Y_BACK1+H/2) 
draw_arrow(ax, X[2]+W, Y_BACK1+H/2, X[3], Y_BACK1+H/2) 

draw_arrow(ax, X[0]+W/2, Y_CLIENT, X[0]+W/2, Y_BACK1+H)
draw_arrow(ax, X[1]+W/2, Y_CLIENT, X[0]+W*0.8, Y_BACK1+H) 

draw_arrow(ax, X[1]+W/2, Y_BACK1, X[1]+W/2, Y_BACK2+H)     
draw_arrow(ax, X[1]+W*0.3, Y_BACK2, X[0]+W*0.8, Y_DATA+H)  
draw_arrow(ax, X[1]+W*0.7, Y_BACK2, X[1]+W*0.7, Y_DATA+H)  

draw_arrow(ax, X[0]+W/2, Y_BACK1, X[0]+W/2, Y_BACK2+H)   

# 【修改重点】从 GEE 代理服务(左侧) -> 绕过数据库框 -> GEE框(左侧)
draw_elbow_arrow(ax, X[0], Y_BACK2 + H/2, X[0], Y_EXT + H/2, bend_x=0.75)

draw_arrow(ax, X[3]+W/2, Y_BACK1, X[3]+W/2, Y_DATA+H)    
draw_arrow(ax, X[2]+W/2, Y_BACK1, X[2]+W/2, Y_BACK2+H)   
draw_arrow(ax, X[2]+W/2, Y_BACK2, X[2]+W/2, Y_DATA+H)    

# ==========================================
# 7. 右侧信息侧边栏 (图例与关键决策)
# ==========================================
# 侧边栏背景 (自适应高度调整)
rect_side = FancyBboxPatch((14.4, 0.2), 3.4, 11.5, boxstyle="round,pad=0.05,rounding_size=0.15",
                           facecolor='#F8FAFC', edgecolor='#CBD5E1', linewidth=1.5, zorder=0)
ax.add_patch(rect_side)

# 侧边栏标题 1
ax.text(14.7, 11.2, '📌 模块图例', fontsize=12, fontweight='bold', color='#0F172A')

legend_items = [
    ('客户端/前端展示', tw['blue_bg'], tw['blue_border']),
    ('后端与基础服务', tw['amber_bg'], tw['amber_border']),
    ('数据与持久化存储', tw['green_bg'], tw['green_border']),
    ('外部第三方依赖', tw['slate_bg'], tw['slate_border']),
    ('核心算法与计算节点', tw['pink_box'], tw['pink_border']),
]
for i, (label, fc, ec) in enumerate(legend_items):
    rect = plt.Rectangle((14.7, 10.5 - i*0.5), 0.35, 0.25, facecolor=fc, edgecolor=ec, linewidth=1.5)
    ax.add_patch(rect)
    ax.text(15.2, 10.62 - i*0.5, label, fontsize=10, va='center', color='#334155')

# 侧边栏标题 2
ax.text(14.7, 7.5, '💡 架构关键决策', fontsize=12, fontweight='bold', color='#0F172A')
decisions = [
    '1. 双模物理隔离:\n   deck.gl 仅负责2D大数据渲染;\n   CesiumJS 专注3D地形与实体。',
    '2. GEE 代理直连模式:\n   后端直接获取瓦片服务 URL;\n   免下载原始庞大数据, 秒开。',
    '3. 算法文件热加载:\n   使用 importlib 动态加载;\n   方便各课题组自由提交脚本。',
    '4. 异步防阻塞队列:\n   Celery 防止长耗时计算卡死;\n   配合 Redis 实现前台状态轮询。',
    '5. 数据分类存储:\n   PostGIS 存结构化边界数据;\n   MinIO 专攻大规模遥感影像。'
]
for i, d in enumerate(decisions):
    ax.text(14.7, 6.5 - i*1.2, d, fontsize=9, color='#475569', linespacing=1.6)

# ==========================================
# 8. 整体大标题
# ==========================================
ax.text(9.0, 12.5, 'Web GIS 架构方案', fontsize=20, fontweight='bold', ha='center', va='center', color='#0F172A')
ax.text(9.0, 12.0, '3D Earth & 2D Map · Real-time Compute · GEE Integration', fontsize=12, ha='center', va='center', color='#64748B')

plt.tight_layout()
# 取消下面的注释即可保存为图片
# plt.savefig(r'Doc\Draw\output\final_tech_stack_optimized_v3.png', dpi=200, bbox_inches='tight', facecolor='white')
plt.show()
print("Professional Tech Stack Diagram Generated.")