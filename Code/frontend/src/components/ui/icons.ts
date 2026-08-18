/**
 * icons.ts — 统一 lucide-vue-next 图标导出
 *
 * 全项目唯一图标入口。组件应从 `@/components/ui/icons` 导入，
 * 而非各自直接 `from 'lucide-vue-next'`，以便：
 * 1. 统一管理图标清单（增删改一处）
 * 2. Tree-shaking 友好（仅导出实际使用的图标）
 * 3. 未来替换图标库时只需改此文件
 *
 * 命名约定：保持 lucide 原始 PascalCase 名称。
 */

export {
  // ── 通用操作 ──
  X,
  Check,
  CheckCircle2,
  Play,
  Save,
  Trash2,
  Settings,
  User,
  RefreshCw,
  ArrowRight,
  ArrowLeft,
  Undo2,
  Minus,
  // ── 导航 / 折叠 ──
  ChevronDown,
  ChevronUp,
  Menu,
  Maximize2,
  Minimize2,
  // ── 信息 / 状态 ──
  Info,
  AlertCircle,
  AlertTriangle,
  XCircle,
  Copy,
  Eye,
  EyeOff,
  ClipboardCheck,
  // ── 加载 ──
  LoaderCircle,
  // ── 图层 / 地图 ──
  Map,
  Satellite,
  Globe,
  Moon,
  Mountain,
  Crosshair,
  Ruler,
  Diamond,
  CircleDot,
  Circle,
  // ── 天气 ──
  Sun,
  Cloud,
  CloudSun,
  CloudLightning,
  // ── 工作流 ──
  ClipboardList,
  Zap,
  Rocket,
  Timer,
  AlarmClock,
  CircleSlash,
  Star,
  Clock,
  Lock,
  Gem,
  Hexagon,
  LayoutGrid,
  Square,
  Ban,
  Wrench,
  Shuffle,
  Palette,
  // ── 工具栏专用 ──
  Move,
  ScrollText,
  Camera,
  Workflow,
  Pen,
  // ── 数据 / 传输 ──
  Table2,
  Folder,
  FolderOpen,
  Link,
  Upload,
  Download,
  Database,
  Server,
  Microscope,
  Package,
  BarChart3,
  TrendingUp,
  // ── 设置 / 账户 ──
  Key,
  DollarSign,
  Gift,
  HelpCircle,
} from 'lucide-vue-next'
