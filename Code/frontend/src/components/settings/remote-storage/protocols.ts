/**
 * 远程存储协议元数据（与后端 ALLOWED_PROTOCOLS / PROTOCOLS_BROWSABLE 对齐）。
 *
 * hostField 语义：url 协议（http/https/filebrowser）host 存 Base URL；
 * path 协议（lan/nfs）host 存 UNC/挂载点；其余存主机名/IP。
 */

import type { RemoteStorageProtocol } from '../../../types/api-reexports'

export interface ProtocolMeta {
  value: RemoteStorageProtocol
  label: string
  /** host 字段的展示标签 */
  hostLabel: string
  hostPlaceholder: string
  /** 留空端口时的建议值（仅提示，不强制） */
  defaultPort: number | null
  /** host 存 URL 的协议（表单提示 + 双路径 alt_url 字段启用） */
  usesUrl: boolean
  /** host 存本机路径/UNC 的协议（不提供备用主机，只提供备用路径） */
  usesPath: boolean
  browsable: boolean
  searchable: boolean
  hint: string
}

export const PROTOCOL_META: Record<RemoteStorageProtocol, ProtocolMeta> = {
  sftp: {
    value: 'sftp',
    label: 'SFTP · SSH 文件传输',
    hostLabel: '主机',
    hostPlaceholder: '192.168.1.10',
    defaultPort: 22,
    usesUrl: false,
    usesPath: false,
    browsable: true,
    searchable: true,
    hint: '密码与私钥二选一；私钥支持 RSA/Ed25519/ECDSA PEM。',
  },
  ssh: {
    value: 'ssh',
    label: 'SSH · 远程命令',
    hostLabel: '主机',
    hostPlaceholder: '192.168.1.10',
    defaultPort: 22,
    usesUrl: false,
    usesPath: false,
    browsable: true,
    searchable: true,
    hint: '算法包远程拉取使用；浏览/搜索同 SFTP 通道。',
  },
  smb: {
    value: 'smb',
    label: 'SMB · Windows 共享',
    hostLabel: '主机',
    hostPlaceholder: '192.168.1.20',
    defaultPort: 445,
    usesUrl: false,
    usesPath: false,
    browsable: true,
    searchable: true,
    hint: '必填默认 Share；URI 形如 smb://host/share/path?cred=profile。',
  },
  ftp: {
    value: 'ftp',
    label: 'FTP',
    hostLabel: '主机',
    hostPlaceholder: '192.168.1.30',
    defaultPort: 21,
    usesUrl: false,
    usesPath: false,
    browsable: true,
    searchable: true,
    hint: '明文协议，仅限可信内网；跨公网请改用 FTPS/SFTP。',
  },
  ftps: {
    value: 'ftps',
    label: 'FTPS · FTP over TLS',
    hostLabel: '主机',
    hostPlaceholder: 'data.example.edu',
    defaultPort: 990,
    usesUrl: false,
    usesPath: false,
    browsable: true,
    searchable: true,
    hint: '显式 TLS（FTP_TLS），端口默认 990。',
  },
  http: {
    value: 'http',
    label: 'HTTP · 只读目录',
    hostLabel: 'Base URL',
    hostPlaceholder: 'http://data.example.org/archive/',
    defaultPort: null,
    usesUrl: true,
    usesPath: false,
    browsable: true,
    searchable: false,
    hint: '解析 HTML 目录列表；不支持名称搜索。',
  },
  https: {
    value: 'https',
    label: 'HTTPS · 只读目录',
    hostLabel: 'Base URL',
    hostPlaceholder: 'https://data.example.org/archive/',
    defaultPort: null,
    usesUrl: true,
    usesPath: false,
    browsable: true,
    searchable: false,
    hint: '解析 HTML 目录列表；可配 Basic 认证。',
  },
  filebrowser: {
    value: 'filebrowser',
    label: 'FileBrowser · Web 文件管理器',
    hostLabel: 'Base URL',
    hostPlaceholder: 'http://192.168.1.40:8080',
    defaultPort: null,
    usesUrl: true,
    usesPath: false,
    browsable: true,
    searchable: true,
    hint: '使用 FileBrowser API（账号密码登录获取 token）。',
  },
  lan: {
    value: 'lan',
    label: '局域网共享 · UNC/挂载点',
    hostLabel: 'UNC / 挂载点路径',
    hostPlaceholder: '\\\\nas\\data 或 /mnt/nas',
    defaultPort: null,
    usesUrl: false,
    usesPath: true,
    browsable: true,
    searchable: true,
    hint: '经操作系统已挂载/可直访的共享路径；跨平台用各自的挂载点语法。',
  },
  nfs: {
    value: 'nfs',
    label: 'NFS · 挂载导出',
    hostLabel: '挂载点路径',
    hostPlaceholder: '/mnt/nfs/export',
    defaultPort: null,
    usesUrl: false,
    usesPath: true,
    browsable: true,
    searchable: true,
    hint: '需先在操作系统完成 NFS 挂载；本协议只负责配置根路径。',
  },
  gs: {
    value: 'gs',
    label: 'Google Cloud Storage',
    hostLabel: 'Bucket',
    hostPlaceholder: 'gcp-public-data-landsat',
    defaultPort: null,
    usesUrl: false,
    usesPath: false,
    browsable: true,
    searchable: true,
    hint: '凭据填 Service Account JSON（整段粘贴）。',
  },
}

export const PROTOCOL_ORDER: RemoteStorageProtocol[] = [
  'sftp',
  'ssh',
  'smb',
  'ftp',
  'ftps',
  'http',
  'https',
  'filebrowser',
  'lan',
  'nfs',
  'gs',
]

/** 该协议是否支持配置「备用访问路径」（gs 无意义——URL 由凭据决定）。 */
export function protocolSupportsAlt(protocol: RemoteStorageProtocol): boolean {
  return protocol !== 'gs'
}

export function protocolMeta(protocol: string): ProtocolMeta | undefined {
  return PROTOCOL_META[protocol as RemoteStorageProtocol]
}
