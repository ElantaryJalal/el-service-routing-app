/**
 * EL Service design tokens — React Native expression.
 *
 * Single source of truth for color, type, spacing, radius, elevation, and
 * motion in the field app. The same values (same names, same meaning) live in
 * dashboard/app/tokens.css for the office dashboard; change them together.
 * See DESIGN.md at the repo root.
 *
 * Foundation only for now: no screen imports this yet. New/touched styles
 * should reference these tokens instead of literal values.
 */

import { Platform, type TextStyle, type ViewStyle } from 'react-native';

/* ---- primitives (not exported): cool neutral grays, brand ramp, status hues ---- */
const gray = {
  white: '#ffffff',
  g50: '#f6f8fb',
  g100: '#eef2f7',
  g200: '#dde4ee',
  g300: '#c3cede',
  g400: '#9aa4b2',
  g500: '#5b6b84',
  g700: '#33465f',
  g900: '#16233a',
} as const;

const blue = {
  b50: '#e8eefc',
  b100: '#dbe5fb',
  b200: '#bccff7',
  b600: '#1d4ed8',
  b800: '#1e40af',
  b900: '#1a3a9e',
} as const;

export const color = {
  /* surfaces & text */
  bg: gray.g50,
  surface: gray.white,
  border: gray.g200,
  borderStrong: gray.g300,
  text: gray.g900,
  textMuted: gray.g500,
  textFaint: gray.g400, // placeholders, disabled

  /* the ONE brand accent */
  brand: blue.b800,
  brandHover: blue.b900,
  brandSoft: blue.b50, // selected rows, active segments
  brandRing: blue.b100, // soft focus halo
  onBrand: gray.white,

  /* tour/stop lifecycle status */
  status: {
    draft: '#64748b',
    draftSoft: '#eef1f5',
    planned: '#1d4ed8',
    plannedSoft: '#e5edff',
    assigned: '#7c3aed',
    assignedSoft: '#f1e8ff',
    inProgress: '#b45309',
    inProgressSoft: '#fdf0dd',
    done: '#15803d',
    doneSoft: '#e4f5ea',
    overdue: '#dc2626',
    overdueSoft: '#fdf1f1',
  },

  /* feedback (banners, form errors, sync notices) */
  success: '#15803d',
  successBg: '#eefaf1',
  successBorder: '#b9e4c5',
  successText: '#135e2c',
  warning: '#b45309',
  warningBg: '#fff8ec',
  warningBorder: '#f0d49b',
  warningText: '#7a4d06',
  danger: '#dc2626',
  dangerBg: '#fdf1f1',
  dangerBorder: '#eebbbb',
  dangerText: '#8f1d1d',
  info: '#1d4ed8',
  infoBg: '#e5edff',
  infoBorder: blue.b200,
  infoText: blue.b800,

  /* categorical day/route scale (maps, charts) — index with dayColor() */
  day: [
    '#1f6feb',
    '#e8590c',
    '#2f9e44',
    '#9c36b5',
    '#e03131',
    '#0c8599',
    '#f08c00',
  ],
} as const;

/* ---- typography ---- */
export const font = {
  /* System sans everywhere; RN uses the platform default automatically. */
  mono: Platform.select({ ios: 'Menlo', android: 'monospace', default: 'monospace' }),
  size: {
    xs: 11.5, // captions, helper notes
    label: 12, // uppercase labels
    sm: 12.5, // secondary text, sub-lines
    data: 13.5, // dense data rows
    base: 14, // body
    md: 15, // section headings, emphasized body
    lg: 17, // step up; reserved
    xl: 20, // screen titles
    xxl: 24, // reserved
    kpi: 28, // KPI values — large, heavy, tabular
  },
  /* Web weights 400/550/650/700 map to the RN-supported ladder. */
  weight: {
    regular: '400',
    medium: '500',
    semibold: '600',
    bold: '700',
  } satisfies Record<string, TextStyle['fontWeight']>,
  trackingLabel: 0.4, // letterSpacing paired with uppercase labels
} as const;

/* ---- spacing: 4px grid ---- */
export const space = {
  s1: 4,
  s2: 8,
  s3: 12,
  s4: 16,
  s5: 20,
  s6: 24,
  s8: 32,
  s12: 48,
} as const;

/* ---- radius: restrained ---- */
export const radius = {
  sm: 6, // buttons, inputs, chips
  md: 8, // cards, sheets, map frame
  full: 999, // pill badges
} as const;

/* ---- elevation: borders do the work; shadows stay low ---- */
export const shadow = {
  sm: {
    shadowColor: gray.g900,
    shadowOpacity: 0.08,
    shadowRadius: 3,
    shadowOffset: { width: 0, height: 1 },
    elevation: 1,
  },
  md: {
    shadowColor: gray.g900,
    shadowOpacity: 0.1,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 4,
  },
} satisfies Record<string, ViewStyle>;

/* ---- motion: short and quiet ---- */
export const duration = {
  fast: 150, // presses, toggles
  base: 200, // sheet slides, reveals
  slow: 1200, // skeleton pulse only
} as const;

/* ---- interaction geometry ---- */
export const size = {
  touch: 48, // minimum tap target
} as const;

export const theme = { color, font, space, radius, shadow, duration, size } as const;
export default theme;
