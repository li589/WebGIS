# 交付概览：CGDA 数据集与图层综合对照表（导师交付）

## 完成内容
- 熟悉整个 CGDA 项目，以系统图层目录（`Code/backend/app/catalog_seeds/`）为权威事实源，产出面向导师交付的「数据集与图层综合对照表」报告，md + docx 双格式。
- 核心交付物（2 个，位于 `deliverables/`）：
  - `CGDA数据集与图层综合对照表-2026-08-11.docx`（51.9 KB，经 tencent-docx 流水线 S1 创作 → S2 美化 → S3 转换）
  - `CGDA数据集与图层综合对照表-2026-08-11.md`（16.7 KB，同内容 Markdown 版）

## 报告核心内容
- **综合对照表（核心交付）**：系统全部 **41 个目录图层**（17 在线天气 + 24 科研/静态产品），逐条对应「图层名称（display_name）/ 数据集名称（dataset_key）/ 内部分类（category 及课题组子分类）/ 内部 ID（layer_id）」，按 6 大类（weather / research-group / climate / vegetation / landcover / terrain）分组列表。
- **配套说明（8 章）**：四个字段含义与 ID 前缀规则（ref-/prod-/method-/obs-/imported-）、数据来源体系（星/地/气/辅/开放）、算法引擎（python_provider / overlay_registry / weather_tile）、就绪状态与样例说明、扩展新数据标准流程、阅读指南。
- 数据核对：41 = 17 + 11（课题组）+ 6（气候）+ 2（植被）+ 3（土地利用）+ 2（地形）；系统工作流种子 33 个。

## 关键决策
- 分类字段以 `catalog_seeds/layer_categories.json` 的 6 大类为准（imported 动态类单独说明）。
- 课题组图层按「模型输入 / 模型输出 / 辅助数据」子分类展开。
- 排版采用 business-report 主题（A4、商务蓝、页脚页码、封面独立节），表格承载全部结构化数据。

## 后续可选项
- 如需按导师反馈调整（如增列"分辨率/单位"、按时间范围分组），可基于已生成 HTML 再做美化或编辑。
