import os
import sys
import json

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from local_postgres_engine import get_connection, init_local_schema

def sync_all():
    init_local_schema()
    conn = get_connection()
    cur = conn.cursor()

    # 1. Sync print_settings
    ps_path = os.path.join(root_dir, 'fetcheddata', 'print_settings.json')
    if os.path.exists(ps_path):
        with open(ps_path, 'r', encoding='utf-8') as f:
            ps = json.load(f)
        
        # Get existing columns in print_settings table
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'print_settings';
        """)
        existing_cols = {row[0] for row in cur.fetchall()}
        
        cur.execute('DELETE FROM public.print_settings;')
        cols = [k for k in ps.keys() if k in existing_cols and k not in ('created_at', 'updated_at')]
        if 'id' not in cols and 'id' in existing_cols:
            cols.append('id')
            ps['id'] = 1
        col_names = ', '.join([f'"{c}"' for c in cols])
        placeholders = ', '.join(['%s'] * len(cols))
        vals = [ps[c] for c in cols]
        cur.execute(f'INSERT INTO public.print_settings ({col_names}) VALUES ({placeholders});', vals)
        print('Synced print_settings table')

    # 2. Sync print_layouts
    pl_path = os.path.join(root_dir, 'fetcheddata', 'print_layouts.json')
    if os.path.exists(pl_path):
        with open(pl_path, 'r', encoding='utf-8') as f:
            pl = json.load(f)
        cur.execute('''
            INSERT INTO public.app_settings (setting_type, payload, updated_by, updated_at)
            VALUES ('print_layouts', %s::jsonb, 'import', now())
            ON CONFLICT (setting_type) DO UPDATE SET payload = EXCLUDED.payload, updated_at = now();
        ''', (json.dumps(pl),))
        print(f'Synced print_layouts into app_settings ({len(pl)} layouts)')

    # 3. Sync remarks
    rem_path = os.path.join(root_dir, 'fetcheddata', 'remarks.json')
    if os.path.exists(rem_path):
        with open(rem_path, 'r', encoding='utf-8') as f:
            remarks = json.load(f)
        if isinstance(remarks, list) and len(remarks):
            cur.execute('DELETE FROM public.remarks;')
            for r in remarks:
                cur.execute('''
                    INSERT INTO public.remarks (id, remark, test_name, category, is_active, usage_count)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                ''', (r.get('id'), r.get('remark'), r.get('test_name'), r.get('category'), r.get('is_active', True), r.get('usage_count', 0)))
            print(f'Synced {len(remarks)} remarks')

    # 4. Sync shifts
    sh_path = os.path.join(root_dir, 'fetcheddata', 'shifts.json')
    if os.path.exists(sh_path):
        with open(sh_path, 'r', encoding='utf-8') as f:
            shifts = json.load(f)
        if isinstance(shifts, list) and len(shifts):
            cur.execute('DELETE FROM public.shifts;')
            for s in shifts:
                cur.execute('''
                    INSERT INTO public.shifts (id, shift, start_time, end_time, created_by)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                ''', (s.get('id'), s.get('shift'), s.get('start_time'), s.get('end_time'), s.get('created_by')))
            print(f'Synced {len(shifts)} shifts')

    conn.commit()
    cur.close()
    conn.close()
    print('All database sync complete!')

if __name__ == '__main__':
    sync_all()
