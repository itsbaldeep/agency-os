"""Bounded draft image discovery. Publication and human review stay separate."""
import copy
import hashlib
import json
import os
from datetime import datetime, timezone

import psycopg2.extras
import content_assets
import content_quality
import editorial_image_suggestions as planner

MAX_SLOTS, MAX_QUERIES, MAX_CANDIDATES = 4, 2, 5


def fingerprint(item):
    value = {key: copy.deepcopy(item.get(key)) for key in
             ('title', 'status', 'content_blocks', 'body', 'structured')}
    if isinstance(value['structured'], dict):
        value['structured'].pop('asset_suggestions', None)
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), default=str).encode()).hexdigest()


def replace_image_body(body, old_block, new_block):
    """Keep Markdown export and typed blocks consistent, including captions."""
    text, old = str(body or ''), old_block or {}
    url = new_block.get('url') or new_block.get('image_url')
    if not url:
        return text
    replacement = f"![{new_block.get('alt', '')}]({url})"
    if new_block.get('caption'):
        replacement += '\n\n' + new_block['caption']
    old_url = old.get('url') or old.get('image_url')
    marker = (f"![{old.get('alt', '')}]({old_url})" if old_url
              else f"_[Image planned: {old.get('alt', '')}]_")
    if old_url and old.get('caption') and marker + '\n\n' + old['caption'] in text:
        marker += '\n\n' + old['caption']
    if marker in text:
        return text.replace(marker, replacement, 1)
    if replacement in text:
        return text
    if old_url and old_url in text:
        raise ValueError('Image Markdown changed outside the editor. Reconcile the draft before replacing it.')
    return text.rstrip() + '\n\n' + replacement


def _cursor(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def _unique(candidates):
    result, seen = [], set()
    for candidate in candidates:
        provenance = candidate.get('provenance') or {}
        provider_id = candidate.get('provider_id') or provenance.get('provider_id')
        key = ('stock:' + str(provider_id)) if provider_id else candidate.get('url') or candidate.get('sha256')
        if key not in seen:
            seen.add(key)
            result.append(candidate)
    return result


def handle(task, get_conn):
    params = task.get('params') or {}
    content_id = params.get('content_item_id')
    if not content_id:
        return {'ok': False, 'error': 'Image suggestions require a content item.'}
    conn = get_conn()
    try:
        cur = _cursor(conn)
        cur.execute('SELECT ci.*,p.lifecycle FROM content_items ci JOIN brands b ON b.id=ci.brand_id '
                    'JOIN projects p ON p.id=b.project_id WHERE ci.id=%s', (content_id,))
        item = cur.fetchone()
        if not item or item.get('status') != 'draft' or item.get('lifecycle') != 'active':
            return {'ok': False, 'error': 'Image suggestions require a draft in an active project.'}
        before = fingerprint(item)
        if params.get('expected_fingerprint') and params['expected_fingerprint'] != before:
            return {'ok': False, 'error': 'Draft changed before image discovery. Refresh suggestions.'}
        blocks = item.get('content_blocks')
        if not isinstance(blocks, list) or not all(isinstance(b, dict) for b in blocks) or not isinstance(item.get('structured') or {}, dict):
            return {'ok': False, 'error': 'Draft requires valid typed blocks and metadata.'}
        if len(json.dumps(item, default=str)) > 300000:
            return {'ok': False, 'error': 'Draft exceeds the bounded image-planning size.'}
        cur.execute('SELECT id,metadata FROM content_assets WHERE brand_id=%s ORDER BY id DESC LIMIT 100', (item['brand_id'],))
        library = [{**r['metadata'], 'id': r['id'], 'asset_id': r['id'], 'source': 'project'}
                   for r in cur.fetchall() if isinstance(r.get('metadata'), dict) and r['metadata'].get('sha256')]
    finally:
        conn.close()

    slots = [(i, b) for i, b in enumerate(blocks) if b.get('type') == 'image_slot']
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'slots': [],
              'skipped_slots': [i for i, _ in slots[MAX_SLOTS:]],
              'matching': 'description metadata only; human visual review required'}
    cache, defaults = {}, {}
    for index, block in slots[:MAX_SLOTS]:
        intent = planner.derive_query(block, item.get('title') or '')
        queries = list(dict.fromkeys([intent['query'], ' '.join(intent['query'].split()[:4])]))[:MAX_QUERIES]
        queries = [q for q in queries if len(q) >= 3]
        stock, provider_state = [], 'not_needed'
        if intent['stock_appropriate']:
            provider_state = 'unavailable' if not os.environ.get('PEXELS_API_KEY') else 'no_results_or_unavailable'
            if os.environ.get('PEXELS_API_KEY'):
                for query in queries:
                    if query not in cache:
                        try:
                            cache[query] = content_assets.search_assets(query)
                        except Exception:
                            cache[query] = []
                    stock.extend(cache[query])
                if stock:
                    provider_state = 'results_available'
        current = planner._current_candidate(block)
        candidates = _unique(([current] if current else []) + library + stock)
        suggestion = planner.build_suggestion(block, candidates, item.get('title') or '', MAX_CANDIDATES)
        entry = {'index': index, 'queries': queries, 'candidates': suggestion['candidates'],
                 'provider_state': provider_state, 'status': 'preserved' if current else 'no_match',
                 'reason': 'Existing image preserved. Alternatives are suggestions, not visual verification.' if current
                 else 'No suitable default found. Review alternatives or upload an image.'}
        if not current and (block.get('url') or block.get('image_url')):
            entry.update(status='preserved', reason='Existing image preserved; review its storage and metadata.')
        elif not current:
            selected = suggestion.get('default')
            if selected and selected.get('kind') == 'stock':
                try:
                    selected = content_assets.import_stock(selected['provider_id'])
                except Exception:
                    selected = None
                    entry.update(status='import_failed', reason='Default image could not be imported. Choose another candidate or retry.')
            elif selected:
                try:
                    content_assets.read_core_asset(selected)
                    content_assets.verify_public_asset(selected['url'], selected['sha256'])
                except Exception:
                    selected = None
                    entry.update(status='asset_unavailable', reason='Suggested library image failed storage verification. Choose another image or retry.')
            if selected and selected.get('sha256') and selected.get('url'):
                defaults[index] = selected
                entry.update(status='selected', reason='Suggested default is embedded in the draft. Confirm it with Use this image, or choose an alternative.')
            elif suggestion.get('needs_custom_visual'):
                entry.update(status='needs_custom_asset', reason='This brief needs a custom diagram or illustration. Stock photography cannot replace it.')
            elif not stock and provider_state != 'not_needed':
                entry['reason'] += ' Stock search returned no results or is unavailable.'
        report['slots'].append(entry)

    conn = get_conn()
    try:
        cur = _cursor(conn)
        cur.execute('SELECT ci.*,p.lifecycle FROM content_items ci JOIN brands b ON b.id=ci.brand_id '
                    'JOIN projects p ON p.id=b.project_id WHERE ci.id=%s FOR UPDATE OF ci', (content_id,))
        current = cur.fetchone()
        if not current or current.get('status') != 'draft' or current.get('lifecycle') != 'active' or fingerprint(current) != before:
            conn.rollback()
            return {'ok': False, 'error': 'Draft changed during discovery. No article changes applied. Refresh suggestions.'}
        updated = copy.deepcopy(blocks)
        structured = copy.deepcopy(current.get('structured') or {})
        body = current.get('body') or ''
        for index, selected in defaults.items():
            cur.execute('INSERT INTO content_assets(brand_id,content_item_id,sha256,metadata) VALUES (%s,%s,%s,%s) '
                        'ON CONFLICT (brand_id,sha256) DO UPDATE SET sha256=EXCLUDED.sha256 RETURNING id,metadata',
                        (item['brand_id'], content_id, selected['sha256'], json.dumps(selected)))
            registered = cur.fetchone()
            asset = {**registered['metadata'], 'id': registered['id'], 'reviewed': False, 'selection_source': 'automatic'}
            updated[index] = {**blocks[index], 'url': asset['url'], 'alt': asset['alt'],
                              'caption': selected.get('caption') or '', 'asset': asset,
                              'reviewed': False, 'selection_source': 'automatic'}
            body = replace_image_body(body, blocks[index], updated[index])
            if 'visual_base_body' in structured:
                structured['visual_base_body'] = replace_image_body(structured['visual_base_body'], blocks[index], updated[index])
            entry = next(s for s in report['slots'] if s['index'] == index)
            entry['candidates'] = _unique([{**asset, 'kind': 'library', 'current': True,
                                           'caption': updated[index]['caption'], 'thumbnail_url': asset['url']}] + entry['candidates'])[:MAX_CANDIDATES]
        if defaults:
            structured['quality_report'] = content_quality.validate_content(updated, 'publish')
            structured.pop('link_report', None)
        report['fingerprint'] = fingerprint({**current, 'content_blocks': updated, 'body': body, 'structured': structured})
        structured['asset_suggestions'] = report
        cur.execute('UPDATE content_items SET content_blocks=%s,body=%s,structured=%s,updated_at=now() WHERE id=%s',
                    (json.dumps(updated), body, json.dumps(structured), content_id))
        conn.commit()
    finally:
        conn.close()
    snapshot = {k: item.get(k) for k in ('body', 'content_blocks', 'structured')} if defaults else None
    return {'ok': True, 'content_item_id': content_id, 'content': json.dumps({
        'before_fingerprint': before, 'before_snapshot': snapshot, 'defaults_changed': len(defaults),
        'slots': len(report['slots']), 'skipped_slots': report['skipped_slots'], 'publication': False}),
        'prompt_tokens': 0, 'completion_tokens': 0, 'cost': 0, 'model': 'deterministic'}
