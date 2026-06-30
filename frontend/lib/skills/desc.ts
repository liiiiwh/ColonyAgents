/** Pick a skill's list description by current UI language.
 *
 *  When both the default `description` and the optional English `description_en` are
 *  non-empty, show the one matching the language; otherwise always fall back to
 *  `description` (so an empty/absent English description changes nothing).
 */
export function pickSkillDesc(
  s: { description: string; description_en?: string | null },
  lang: string | undefined,
): string {
  if (lang?.startsWith('en') && s.description_en) return s.description_en;
  return s.description;
}
