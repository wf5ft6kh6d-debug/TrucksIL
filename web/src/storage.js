// Vehicle profiles in localStorage (US-01). Storage is injected so it is testable in Node.
export const STORAGE_KEY = 'trucksil.profiles.v1';

export function loadProfiles(storage) {
  try {
    const v = JSON.parse(storage.getItem(STORAGE_KEY) || '[]');
    return Array.isArray(v) ? v.filter((p) => p && typeof p.profileName === 'string') : [];
  } catch { return []; }
}

/** Inserts or replaces (by profileName) and persists. Returns the new list. */
export function saveProfile(storage, profile) {
  const list = loadProfiles(storage).filter((p) => p.profileName !== profile.profileName);
  list.push(profile);
  list.sort((a, b) => a.profileName.localeCompare(b.profileName));
  storage.setItem(STORAGE_KEY, JSON.stringify(list));
  return list;
}

export function deleteProfile(storage, name) {
  const list = loadProfiles(storage).filter((p) => p.profileName !== name);
  storage.setItem(STORAGE_KEY, JSON.stringify(list));
  return list;
}
