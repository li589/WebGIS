/**
 * Runtime brand resolution: logged-in theme > primary public theme > static BRAND.
 */
import { computed, type Ref } from 'vue'

import { BRAND } from '../ui-copy/brand'
import type { ThemePublic } from '../services/auth-api'

export type ResolvedBrand = {
  shortName: string
  fullName: string
  displayNameEn: string
  abbr: string
  eyebrow: string
  description: string
  logoUrl: string | null
}

export function brandFromTheme(theme: ThemePublic | null | undefined): ResolvedBrand | null {
  if (!theme) return null
  return {
    shortName: theme.name_zh || BRAND.shortName,
    fullName: theme.full_name_zh || BRAND.fullName,
    displayNameEn: theme.name_en || BRAND.displayNameEn,
    abbr: theme.abbr || BRAND.abbr,
    eyebrow: theme.abbr || BRAND.eyebrow,
    description: theme.description || '',
    logoUrl: theme.logo_url ?? null,
  }
}

export function staticBrand(): ResolvedBrand {
  return {
    shortName: BRAND.shortName,
    fullName: BRAND.fullName,
    displayNameEn: BRAND.displayNameEn,
    abbr: BRAND.abbr,
    eyebrow: BRAND.eyebrow,
    description: '',
    logoUrl: null,
  }
}

export function applyDocumentTitle(fullName: string) {
  if (typeof document !== 'undefined') {
    document.title = fullName
  }
}

export function useResolvedBrand(
  activeTheme: Ref<ThemePublic | null>,
  primaryTheme: Ref<ThemePublic | null>,
) {
  return computed<ResolvedBrand>(() => {
    return (
      brandFromTheme(activeTheme.value) ??
      brandFromTheme(primaryTheme.value) ??
      staticBrand()
    )
  })
}
