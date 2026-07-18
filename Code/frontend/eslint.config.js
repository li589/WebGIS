// Sprint 4.3: ESLint 9+ flat config
//
// 设计原则：
//   1. 严格但不过度：启用 recommended 规则集，关闭纯风格类规则（由 Prettier 负责）
//   2. TypeScript 优先：类型相关规则从 @typescript-eslint 派生
//   3. Vue 3 现代语法：使用 vue3-recommended，禁用 Vue 2 兼容规则
//   4. 与 Prettier 协作：eslint-config-prettier 关闭所有与 Prettier 冲突的规则
//
// 使用：
//   npm run lint        # 检查
//   npm run lint:fix    # 自动修复
//   npm run format      # Prettier 格式化

import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import pluginVue from 'eslint-plugin-vue'
import prettierConfig from 'eslint-config-prettier'
import globals from 'globals'

export default tseslint.config(
  // ── 全局忽略 ──────────────────────────────────────────────────────────
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      'src/types/api-contracts.ts',     // OpenAPI 自动生成
      'src/types/api-reexports.ts',     // 自动生成
      'vite.config.ts',
      'vitest.config.ts',
    ],
  },

  // ── 基础 recommended 规则 ────────────────────────────────────────────
  js.configs.recommended,

  // ── TypeScript recommended（类型感知规则） ───────────────────────────
  ...tseslint.configs.recommended,

  // ── Vue 3 recommended（含 <script setup> 支持） ─────────────────────
  ...pluginVue.configs['flat/recommended'],

  // ── 项目自定义规则 ───────────────────────────────────────────────────
  {
    files: ['src/**/*.{ts,tsx,vue,js,jsx}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: {
        ...globals.browser,   // window, document, HTMLElement, AbortController 等
        ...globals.es2021,    // Promise, Set, Map 等内置对象
      },
      parserOptions: {
        parser: tseslint.parser,  // Vue 文件中 <script lang="ts"> 用 TS parser
      },
    },
    rules: {
      // ── 严格但实用的规则 ──────────────────────────────────────────────
      'no-console': ['warn', { allow: ['warn', 'error'] }],  // 允许 warn/error，警告 info/log
      'no-debugger': 'error',
      'no-undef': 'off',  // TypeScript 已通过 vue-tsc 检查未定义变量，避免误报浏览器全局
      'no-unused-vars': 'off',  // 由 @typescript-eslint/no-unused-vars 接管
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],
      '@typescript-eslint/no-explicit-any': 'warn',  // 警告而非错误，逐步收紧
      // 关闭 consistent-type-imports：现有代码大量使用 import() 类型表达式（如 JSDoc），
      // 强制 inline-type-imports 会产生大量噪音。改用 vue-tsc 做类型检查即可。
      '@typescript-eslint/consistent-type-imports': 'off',

      // ── Vue 规则 ──────────────────────────────────────────────────────
      'vue/multi-word-component-names': 'off',  // 允许单词组件名（如 Views.vue）
      'vue/no-v-html': 'off',                   // 项目内可信内容
      'vue/require-default-prop': 'off',        // TS 类型已表达可选性
      'vue/attribute-hyphenation': ['error', 'always'],
      'vue/component-name-in-template-casing': ['error', 'PascalCase'],
      // attributes-order 与现有代码风格不一致（项目习惯 class 在前），
      // 改为 warning 而非 error，逐步推进
      'vue/attributes-order': 'warn',

      // ── 关闭与 Prettier 冲突的规则 ────────────────────────────────────
      // eslint-config-prettier 已在最后 disable，这里不重复
    },
  },

  // ── 测试文件宽松处理 ─────────────────────────────────────────────────
  {
    files: ['src/**/*.test.{ts,tsx}', 'src/**/*.spec.{ts,tsx}', 'tests/**/*.{ts,tsx}'],
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
      'no-console': 'off',
    },
  },

  // ── Prettier 兼容层（必须放在最后） ──────────────────────────────────
  prettierConfig,
)
