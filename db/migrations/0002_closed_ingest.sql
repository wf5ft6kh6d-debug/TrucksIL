-- CANDIDATE ONLY: apply via scripts/migrate_stage2.py to empty disposable DB.
-- There is no trusted ingest adapter yet. Reject ALL restriction writes rather
-- than accept a client-supplied 'validated' flag or an incomplete SQL validator.
SET LOCAL search_path = trucksil_stage2, public;
REVOKE ALL ON ALL TABLES IN SCHEMA trucksil_stage2 FROM PUBLIC;
REVOKE ALL ON SCHEMA trucksil_stage2 FROM PUBLIC;

CREATE FUNCTION trucksil_stage2.block_restriction_write() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Restriction writes disabled: controlled ingest adapter not implemented'
        USING ERRCODE = '42501';
END;
$$;
CREATE TRIGGER closed_restriction_ingest
BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON trucksil_stage2.restriction_staging
FOR EACH STATEMENT EXECUTE FUNCTION trucksil_stage2.block_restriction_write();

ALTER TABLE trucksil_stage2.audit_events ADD COLUMN entity_key jsonb;
ALTER TABLE trucksil_stage2.audit_events ADD COLUMN old_row jsonb;
ALTER TABLE trucksil_stage2.audit_events ADD COLUMN new_row jsonb;
ALTER TABLE trucksil_stage2.audit_events ADD COLUMN transaction_id bigint;
ALTER TABLE trucksil_stage2.audit_events ADD COLUMN session_actor text;
CREATE OR REPLACE FUNCTION trucksil_stage2.audit_staging_change() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, trucksil_stage2 AS $$
DECLARE before_row jsonb; after_row jsonb; row_data jsonb; key_data jsonb;
BEGIN
    IF TG_OP <> 'INSERT' THEN before_row := to_jsonb(OLD); END IF;
    IF TG_OP <> 'DELETE' THEN after_row := to_jsonb(NEW); END IF;
    row_data := coalesce(after_row,before_row);
    key_data := CASE TG_TABLE_NAME
        WHEN 'coverage_reviews' THEN jsonb_build_object('segment_id',row_data->'segment_id','dimension',row_data->'dimension','direction',row_data->'direction')
        WHEN 'restriction_staging' THEN jsonb_build_object('restriction_id',row_data->'restriction_id')
        WHEN 'road_segments' THEN jsonb_build_object('segment_id',row_data->'segment_id')
        WHEN 'road_nodes' THEN jsonb_build_object('node_id',row_data->'node_id')
        WHEN 'sources' THEN jsonb_build_object('source_id',row_data->'source_id')
    END;
    INSERT INTO trucksil_stage2.audit_events
        (entity_table,entity_id,action,entity_key,old_row,new_row,transaction_id,session_actor)
    VALUES (TG_TABLE_NAME,key_data::text,TG_OP,key_data,before_row,after_row,txid_current(),session_user);
    RETURN NULL;
END;
$$;
CREATE FUNCTION trucksil_stage2.block_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Audit history is append-only' USING ERRCODE='42501';
END;
$$;
CREATE TRIGGER protect_audit_history BEFORE UPDATE OR DELETE OR TRUNCATE
ON trucksil_stage2.audit_events FOR EACH STATEMENT EXECUTE FUNCTION trucksil_stage2.block_audit_mutation();

CREATE FUNCTION trucksil_stage2.check_segment_identity() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, trucksil_stage2, public AS $$
DECLARE a trucksil_stage2.road_nodes; b trucksil_stage2.road_nodes;
BEGIN
    SELECT * INTO a FROM trucksil_stage2.road_nodes WHERE node_id=NEW.from_node FOR SHARE;
    SELECT * INTO b FROM trucksil_stage2.road_nodes WHERE node_id=NEW.to_node FOR SHARE;
    IF a.node_id IS NULL OR b.node_id IS NULL THEN
        RAISE EXCEPTION 'Missing endpoint node' USING ERRCODE='23503';
    END IF;
    IF a.source_id <> NEW.source_id OR b.source_id <> NEW.source_id
       OR a.source_revision <> NEW.source_revision OR b.source_revision <> NEW.source_revision
       OR NOT ST_Equals(ST_StartPoint(NEW.geometry),a.geometry)
       OR NOT ST_Equals(ST_EndPoint(NEW.geometry),b.geometry) THEN
        RAISE EXCEPTION 'Endpoint geometry/source revision mismatch' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER check_segment_identity BEFORE INSERT OR UPDATE ON trucksil_stage2.road_segments
FOR EACH ROW EXECUTE FUNCTION trucksil_stage2.check_segment_identity();
-- Node identity/geometry is immutable: revisions must receive new node IDs.
CREATE FUNCTION trucksil_stage2.immutable_node_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.node_id IS DISTINCT FROM OLD.node_id OR NEW.source_id IS DISTINCT FROM OLD.source_id
       OR NEW.source_feature_id IS DISTINCT FROM OLD.source_feature_id
       OR NEW.source_revision IS DISTINCT FROM OLD.source_revision
       OR NEW.geometry IS DISTINCT FROM OLD.geometry THEN
        RAISE EXCEPTION 'Create a new node revision instead of mutating identity' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER immutable_node_identity BEFORE UPDATE ON trucksil_stage2.road_nodes
FOR EACH ROW EXECUTE FUNCTION trucksil_stage2.immutable_node_identity();
-- Owners/superusers can disable triggers or alter DDL. Never grant owner roles
-- to ingestion clients; this proposal is not protection against administrators.
