import {useEffect, useState} from "react";

export type AppThemePreference = "system" | "paper" | "warm" | "night";
export type ResolvedAppTheme = Exclude<AppThemePreference, "system">;

export const APP_THEME_STORAGE_KEY = "waypoint:app-theme:v1";

const options: Array<{value: AppThemePreference; label: string; description: string}> = [
  {value: "system", label: "System", description: "Match this device"},
  {value: "paper", label: "Paper", description: "Crisp and neutral"},
  {value: "warm", label: "Warm", description: "Soft cream canvas"},
  {value: "night", label: "Night", description: "Low-light contrast"},
];

export function resolveAppTheme(preference: AppThemePreference, systemIsDark: boolean): ResolvedAppTheme {
  return preference === "system" ? (systemIsDark ? "night" : "paper") : preference;
}

function savedPreference(): AppThemePreference {
  try {
    const saved = localStorage.getItem(APP_THEME_STORAGE_KEY);
    return saved && options.some((option) => option.value === saved) ? saved as AppThemePreference : "system";
  } catch {
    return "system";
  }
}

function systemIsDark() {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function useAppAppearance() {
  const [preference, setPreferenceState] = useState<AppThemePreference>(savedPreference);
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedAppTheme>(() => resolveAppTheme(savedPreference(), systemIsDark()));

  useEffect(() => {
    const media = typeof window.matchMedia === "function" ? window.matchMedia("(prefers-color-scheme: dark)") : null;
    const apply = () => {
      const resolved = resolveAppTheme(preference, Boolean(media?.matches));
      document.documentElement.dataset.appTheme = resolved;
      document.documentElement.style.colorScheme = resolved === "night" ? "dark" : "light";
      setResolvedTheme(resolved);
    };
    apply();
    media?.addEventListener?.("change", apply);
    return () => media?.removeEventListener?.("change", apply);
  }, [preference]);

  const setPreference = (next: AppThemePreference) => {
    setPreferenceState(next);
    try {
      localStorage.setItem(APP_THEME_STORAGE_KEY, next);
    } catch {
      // Appearance still changes for this open view when durable storage is unavailable.
    }
  };

  return {preference, resolvedTheme, setPreference};
}

export function AppAppearanceSettings({
  preference,
  resolvedTheme,
  onChange,
}: {
  preference: AppThemePreference;
  resolvedTheme: ResolvedAppTheme;
  onChange: (preference: AppThemePreference) => void;
}) {
  return (
    <section className="panel app-appearance" aria-labelledby="app-appearance-title">
      <div className="panel-head">
        <div>
          <span className="eyebrow">Appearance</span>
          <h2 id="app-appearance-title">Choose Waypoint’s look</h2>
        </div>
        <span className="appearance-current">Using {resolvedTheme}</span>
      </div>
      <p>Changes the application shell on this device. EPUB reader themes remain a separate reading preference.</p>
      <div className="appearance-options" role="radiogroup" aria-label="App appearance">
        {options.map((option) => (
          <button
            key={option.value}
            className={`appearance-option appearance-${option.value}`}
            type="button"
            role="radio"
            aria-checked={preference === option.value}
            onClick={() => onChange(option.value)}
          >
            <span className="appearance-swatch" aria-hidden="true"><i /><i /><i /></span>
            <strong>{option.label}</strong>
            <small>{option.description}</small>
          </button>
        ))}
      </div>
    </section>
  );
}
