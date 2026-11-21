import test from 'node:test';
import assert from 'node:assert/strict';
import { LANGS, STRINGS, t, dirFor, isRtl, resolveLang, applyLang } from '../src/i18n.js';

test('i18n: all four languages define every English key (no missing UI strings)', () => {
  assert.deepEqual([...LANGS].sort(), ['ar', 'en', 'he', 'ru']);
  const keys = Object.keys(STRINGS.en);
  for (const l of LANGS) {
    const missing = keys.filter((k) => typeof STRINGS[l][k] !== 'string' || STRINGS[l][k].trim() === '');
    assert.deepEqual(missing, [], `${l} missing ${missing.join(', ')}`);
    const extra = Object.keys(STRINGS[l]).filter((k) => !(k in STRINGS.en));
    assert.deepEqual(extra, [], `${l} has unknown keys`);
  }
});

test('i18n: dir is rtl for he/ar, ltr for ru/en', () => {
  assert.equal(dirFor('he'), 'rtl');
  assert.equal(dirFor('ar'), 'rtl');
  assert.equal(dirFor('ru'), 'ltr');
  assert.equal(dirFor('en'), 'ltr');
  assert.equal(isRtl('xx'), false);
});

test('i18n: applyLang sets lang and dir attributes', () => {
  const attrs = {};
  const fake = { setAttribute: (k, v) => { attrs[k] = v; } };
  applyLang(fake, 'ar');
  assert.deepEqual(attrs, { lang: 'ar', dir: 'rtl' });
  applyLang(fake, 'ru');
  assert.deepEqual(attrs, { lang: 'ru', dir: 'ltr' });
});

test('i18n: lookup with params, fallback to en, then to key', () => {
  assert.equal(t('ru', 'banner.prototype'), 'Прототип. Не для навигации.');
  assert.equal(t('en', 'err.other', { status: 418 }), 'Unexpected error (418). No route shown.');
  assert.equal(t('xx', 'banner.prototype'), 'Prototype. Not for navigation.');
  assert.equal(t('he', 'no.such.key'), 'no.such.key');
  assert.equal(t('en', 'route.summary', { km: '1.0' }), 'Distance 1.0 km, time {min} min, restriction detours: {reroutes}');
});

test('i18n: safety strings present in every language; posted sign label in ru', () => {
  assert.equal(STRINGS.ru['source.posted_sign'], 'по знаку');
  assert.equal(STRINGS.en['source.posted_sign'], 'posted sign');
  for (const l of LANGS) assert.match(t(l, 'banner.coverage'), /≠/);
});

test('i18n: resolveLang uses stored, then navigator languages (iw -> he), default he', () => {
  assert.equal(resolveLang('ru', ['en-US']), 'ru');
  assert.equal(resolveLang(null, ['fr-FR', 'ar-IL']), 'ar');
  assert.equal(resolveLang(undefined, ['iw']), 'he');
  assert.equal(resolveLang('xx', ['fr']), 'he');
});
