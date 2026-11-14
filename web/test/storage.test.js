import test from 'node:test';
import assert from 'node:assert/strict';
import { STORAGE_KEY, loadProfiles, saveProfile, deleteProfile } from '../src/storage.js';

const mem = () => { const m = new Map(); return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), m }; };

test('storage: save/replace/delete profiles by name', () => {
  const s = mem();
  assert.deepEqual(loadProfiles(s), []);
  saveProfile(s, { profileName: 'B', heightM: 4 });
  saveProfile(s, { profileName: 'A', heightM: 3 });
  saveProfile(s, { profileName: 'B', heightM: 4.1 });
  assert.deepEqual(loadProfiles(s), [{ profileName: 'A', heightM: 3 }, { profileName: 'B', heightM: 4.1 }]);
  deleteProfile(s, 'A');
  assert.deepEqual(loadProfiles(s).map((p) => p.profileName), ['B']);
});

test('storage: corrupt data is ignored, not thrown', () => {
  const s = mem();
  s.setItem(STORAGE_KEY, '{not json');
  assert.deepEqual(loadProfiles(s), []);
  s.setItem(STORAGE_KEY, JSON.stringify([{ x: 1 }, { profileName: 'ok' }]));
  assert.deepEqual(loadProfiles(s), [{ profileName: 'ok' }]);
});
