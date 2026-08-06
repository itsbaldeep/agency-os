--
-- PostgreSQL database dump
--

\restrict a8Pwe5a8DTpxrNhJzSRStBUuwayOnnV0Zt3GvaI8qYC7CRGfOPjtN7wOupmU9Ke

-- Dumped from database version 16.14
-- Dumped by pg_dump version 18.4 (Ubuntu 18.4-0ubuntu0.26.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION vector IS 'vector data type';


--
-- Name: approval_status; Type: TYPE; Schema: public; Owner: agency
--

CREATE TYPE public.approval_status AS ENUM (
    'pending',
    'approved',
    'rejected',
    'executed',
    'failed'
);


ALTER TYPE public.approval_status OWNER TO agency;

--
-- Name: approval_type; Type: TYPE; Schema: public; Owner: agency
--

CREATE TYPE public.approval_type AS ENUM (
    'dns',
    'deploy',
    'content',
    'schema',
    'dependency',
    'other',
    'apex-deploy'
);


ALTER TYPE public.approval_type OWNER TO agency;

--
-- Name: dns_state; Type: TYPE; Schema: public; Owner: agency
--

CREATE TYPE public.dns_state AS ENUM (
    'under_approval',
    'approved',
    'live',
    'rejected',
    'removed'
);


ALTER TYPE public.dns_state OWNER TO agency;

--
-- Name: project_state; Type: TYPE; Schema: public; Owner: agency
--

CREATE TYPE public.project_state AS ENUM (
    'idea',
    'prd',
    'scaffolded',
    'building',
    'preview',
    'staged',
    'live',
    'handed_off',
    'archived',
    'imported'
);


ALTER TYPE public.project_state OWNER TO agency;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: approvals; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.approvals (
    id bigint NOT NULL,
    project_id bigint,
    type public.approval_type NOT NULL,
    payload jsonb NOT NULL,
    status public.approval_status DEFAULT 'pending'::public.approval_status NOT NULL,
    requested_at timestamp with time zone DEFAULT now() NOT NULL,
    decided_at timestamp with time zone,
    executed_at timestamp with time zone,
    note text
);


ALTER TABLE public.approvals OWNER TO agency;

--
-- Name: approvals_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.approvals_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.approvals_id_seq OWNER TO agency;

--
-- Name: approvals_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.approvals_id_seq OWNED BY public.approvals.id;


--
-- Name: audits; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.audits (
    id integer NOT NULL,
    brand_id integer NOT NULL,
    audit_type text NOT NULL,
    summary jsonb,
    raw_data jsonb,
    sources jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    crawl_text text
);


ALTER TABLE public.audits OWNER TO agency;

--
-- Name: audits_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.audits_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.audits_id_seq OWNER TO agency;

--
-- Name: audits_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.audits_id_seq OWNED BY public.audits.id;


--
-- Name: background_jobs; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.background_jobs (
    id integer NOT NULL,
    name text NOT NULL,
    script_path text NOT NULL,
    schedule text DEFAULT '0 * * * *'::text NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    requires_approval boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.background_jobs OWNER TO agency;

--
-- Name: background_jobs_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.background_jobs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.background_jobs_id_seq OWNER TO agency;

--
-- Name: background_jobs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.background_jobs_id_seq OWNED BY public.background_jobs.id;


--
-- Name: brand_embeddings; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.brand_embeddings (
    id integer NOT NULL,
    brand_id integer NOT NULL,
    chunk_text text NOT NULL,
    embedding public.vector(1536),
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.brand_embeddings OWNER TO agency;

--
-- Name: brand_embeddings_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.brand_embeddings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.brand_embeddings_id_seq OWNER TO agency;

--
-- Name: brand_embeddings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.brand_embeddings_id_seq OWNED BY public.brand_embeddings.id;


--
-- Name: brand_pipelines; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.brand_pipelines (
    id integer NOT NULL,
    brand_id integer NOT NULL,
    enabled_stages jsonb DEFAULT '[]'::jsonb NOT NULL,
    intensity text DEFAULT 'normal'::text NOT NULL,
    schedule_cron text DEFAULT '0 6 * * 1'::text,
    access_tier text DEFAULT '0'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.brand_pipelines OWNER TO agency;

--
-- Name: brand_pipelines_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.brand_pipelines_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.brand_pipelines_id_seq OWNER TO agency;

--
-- Name: brand_pipelines_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.brand_pipelines_id_seq OWNED BY public.brand_pipelines.id;


--
-- Name: brand_properties; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.brand_properties (
    id integer NOT NULL,
    brand_id integer NOT NULL,
    property_type text NOT NULL,
    value text NOT NULL,
    accessible boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.brand_properties OWNER TO agency;

--
-- Name: brand_properties_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.brand_properties_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.brand_properties_id_seq OWNER TO agency;

--
-- Name: brand_properties_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.brand_properties_id_seq OWNED BY public.brand_properties.id;


--
-- Name: brands; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.brands (
    id integer NOT NULL,
    name text NOT NULL,
    slug text NOT NULL,
    access_tier text DEFAULT '0'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.brands OWNER TO agency;

--
-- Name: brands_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.brands_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.brands_id_seq OWNER TO agency;

--
-- Name: brands_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.brands_id_seq OWNED BY public.brands.id;


--
-- Name: clients; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.clients (
    id integer NOT NULL,
    name text NOT NULL,
    type text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    brand_id integer,
    project_id integer,
    intake_params jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT clients_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'queued'::text, 'running'::text, 'completed'::text, 'failed'::text, 'pending_implementation'::text]))),
    CONSTRAINT clients_type_check CHECK ((type = ANY (ARRAY['black_box'::text, 'import_repo'::text, 'new_project'::text])))
);


ALTER TABLE public.clients OWNER TO agency;

--
-- Name: clients_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.clients_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.clients_id_seq OWNER TO agency;

--
-- Name: clients_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.clients_id_seq OWNED BY public.clients.id;


--
-- Name: competitors; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.competitors (
    id integer NOT NULL,
    brand_id integer NOT NULL,
    domain text NOT NULL,
    name text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.competitors OWNER TO agency;

--
-- Name: competitors_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.competitors_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.competitors_id_seq OWNER TO agency;

--
-- Name: competitors_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.competitors_id_seq OWNED BY public.competitors.id;


--
-- Name: concept_variations; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.concept_variations (
    id integer NOT NULL,
    project_id bigint,
    brand_id bigint,
    skill character varying(50) NOT NULL,
    brief text NOT NULL,
    spec_index integer NOT NULL,
    spec_json jsonb NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying,
    file_path text,
    task_id bigint,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.concept_variations OWNER TO agency;

--
-- Name: concept_variations_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.concept_variations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.concept_variations_id_seq OWNER TO agency;

--
-- Name: concept_variations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.concept_variations_id_seq OWNED BY public.concept_variations.id;


--
-- Name: content_items; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.content_items (
    id integer NOT NULL,
    brand_id integer NOT NULL,
    title text NOT NULL,
    body text,
    content_type text DEFAULT 'article'::text NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    approval_id integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    suggestion_id integer,
    task_id integer,
    compliance_flags jsonb DEFAULT '[]'::jsonb NOT NULL
);


ALTER TABLE public.content_items OWNER TO agency;

--
-- Name: content_items_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.content_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.content_items_id_seq OWNER TO agency;

--
-- Name: content_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.content_items_id_seq OWNED BY public.content_items.id;


--
-- Name: cover_letters; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.cover_letters (
    id integer NOT NULL,
    listing_id integer,
    campaign_id integer,
    content text,
    recipient_name text,
    recipient_title text,
    company text,
    status text DEFAULT 'draft'::text,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.cover_letters OWNER TO agency;

--
-- Name: cover_letters_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.cover_letters_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.cover_letters_id_seq OWNER TO agency;

--
-- Name: cover_letters_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.cover_letters_id_seq OWNED BY public.cover_letters.id;


--
-- Name: dns_records; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.dns_records (
    id bigint NOT NULL,
    project_id bigint,
    subdomain text NOT NULL,
    target_service text,
    state public.dns_state DEFAULT 'under_approval'::public.dns_state NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.dns_records OWNER TO agency;

--
-- Name: dns_records_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.dns_records_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.dns_records_id_seq OWNER TO agency;

--
-- Name: dns_records_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.dns_records_id_seq OWNED BY public.dns_records.id;


--
-- Name: email_threads; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.email_threads (
    id integer NOT NULL,
    contact_id integer,
    listing_id integer,
    campaign_id integer,
    subject text,
    body text,
    gmail_message_id text,
    direction text DEFAULT 'outbound'::text,
    status text DEFAULT 'draft'::text,
    sent_at timestamp without time zone,
    opened_at timestamp without time zone,
    replied_at timestamp without time zone,
    follow_up_number integer DEFAULT 0,
    is_follow_up boolean DEFAULT false,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.email_threads OWNER TO agency;

--
-- Name: email_threads_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.email_threads_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.email_threads_id_seq OWNER TO agency;

--
-- Name: email_threads_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.email_threads_id_seq OWNED BY public.email_threads.id;


--
-- Name: health_checks; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.health_checks (
    id bigint NOT NULL,
    service_id bigint,
    ts timestamp with time zone DEFAULT now() NOT NULL,
    healthy boolean NOT NULL,
    detail text
);


ALTER TABLE public.health_checks OWNER TO agency;

--
-- Name: health_checks_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.health_checks_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.health_checks_id_seq OWNER TO agency;

--
-- Name: health_checks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.health_checks_id_seq OWNED BY public.health_checks.id;


--
-- Name: job_applications; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.job_applications (
    id integer NOT NULL,
    listing_id integer,
    campaign_id integer,
    resume_id integer,
    cover_letter_id integer,
    contact_id integer,
    status text DEFAULT 'preparing'::text,
    applied_at timestamp without time zone,
    linkedin_sent_at timestamp without time zone,
    email_sent_at timestamp without time zone,
    interview_date timestamp without time zone,
    offer_details text,
    rejection_reason text,
    notes text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.job_applications OWNER TO agency;

--
-- Name: job_applications_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.job_applications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.job_applications_id_seq OWNER TO agency;

--
-- Name: job_applications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.job_applications_id_seq OWNED BY public.job_applications.id;


--
-- Name: job_campaigns; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.job_campaigns (
    id integer NOT NULL,
    name text NOT NULL,
    status text DEFAULT 'draft'::text,
    target_jobs_per_run integer DEFAULT 10,
    run_interval_hours integer DEFAULT 24,
    resume_text text,
    job_titles text[] DEFAULT '{}'::text[],
    locations text[] DEFAULT '{}'::text[],
    company_include text[] DEFAULT '{}'::text[],
    company_exclude text[] DEFAULT '{}'::text[],
    keywords_include text[] DEFAULT '{}'::text[],
    keywords_exclude text[] DEFAULT '{}'::text[],
    min_salary integer,
    max_applications_per_company integer DEFAULT 1,
    linkedin_note_template text,
    cover_letter_template text,
    email_template text,
    follow_up_days integer DEFAULT 5,
    max_follow_ups integer DEFAULT 2,
    gmail_oauth_state text,
    gmail_token text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.job_campaigns OWNER TO agency;

--
-- Name: job_campaigns_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.job_campaigns_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.job_campaigns_id_seq OWNER TO agency;

--
-- Name: job_campaigns_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.job_campaigns_id_seq OWNED BY public.job_campaigns.id;


--
-- Name: job_contacts; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.job_contacts (
    id integer NOT NULL,
    listing_id integer,
    name text,
    title text,
    company text,
    email text,
    linkedin_url text,
    phone text,
    source text DEFAULT 'manual'::text,
    confidence integer DEFAULT 0,
    status text DEFAULT 'pending'::text,
    notes text,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.job_contacts OWNER TO agency;

--
-- Name: job_contacts_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.job_contacts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.job_contacts_id_seq OWNER TO agency;

--
-- Name: job_contacts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.job_contacts_id_seq OWNED BY public.job_contacts.id;


--
-- Name: job_listings; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.job_listings (
    id integer NOT NULL,
    campaign_id integer,
    title text NOT NULL,
    company text NOT NULL,
    location text,
    description text,
    url text,
    salary_range text,
    source text DEFAULT 'manual'::text,
    posted_date date,
    requirements text,
    score integer DEFAULT 0,
    status text DEFAULT 'discovered'::text,
    notes text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.job_listings OWNER TO agency;

--
-- Name: job_listings_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.job_listings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.job_listings_id_seq OWNER TO agency;

--
-- Name: job_listings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.job_listings_id_seq OWNED BY public.job_listings.id;


--
-- Name: job_run_history; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.job_run_history (
    id integer NOT NULL,
    campaign_id integer,
    status text DEFAULT 'running'::text,
    jobs_targeted integer DEFAULT 0,
    jobs_processed integer DEFAULT 0,
    applications_created integer DEFAULT 0,
    emails_sent integer DEFAULT 0,
    linkedin_notes_sent integer DEFAULT 0,
    errors text,
    started_at timestamp without time zone DEFAULT now(),
    completed_at timestamp without time zone
);


ALTER TABLE public.job_run_history OWNER TO agency;

--
-- Name: job_run_history_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.job_run_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.job_run_history_id_seq OWNER TO agency;

--
-- Name: job_run_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.job_run_history_id_seq OWNED BY public.job_run_history.id;


--
-- Name: job_runs; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.job_runs (
    id integer NOT NULL,
    job_id integer,
    triggered_by text DEFAULT 'scheduled'::text NOT NULL,
    status text DEFAULT 'running'::text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    duration_sec integer,
    model text,
    tokens_in integer DEFAULT 0,
    tokens_out integer DEFAULT 0,
    cost_usd numeric(12,6) DEFAULT 0,
    cost_inr numeric(12,6) DEFAULT 0,
    detail text,
    approval_id integer
);


ALTER TABLE public.job_runs OWNER TO agency;

--
-- Name: job_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.job_runs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.job_runs_id_seq OWNER TO agency;

--
-- Name: job_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.job_runs_id_seq OWNED BY public.job_runs.id;


--
-- Name: keywords; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.keywords (
    id integer NOT NULL,
    brand_id integer NOT NULL,
    keyword text NOT NULL,
    volume_est integer,
    difficulty integer,
    current_rank integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.keywords OWNER TO agency;

--
-- Name: keywords_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.keywords_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.keywords_id_seq OWNER TO agency;

--
-- Name: keywords_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.keywords_id_seq OWNED BY public.keywords.id;


--
-- Name: linkedin_notes; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.linkedin_notes (
    id integer NOT NULL,
    contact_id integer,
    listing_id integer,
    campaign_id integer,
    content text,
    status text DEFAULT 'draft'::text,
    sent_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.linkedin_notes OWNER TO agency;

--
-- Name: linkedin_notes_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.linkedin_notes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.linkedin_notes_id_seq OWNER TO agency;

--
-- Name: linkedin_notes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.linkedin_notes_id_seq OWNED BY public.linkedin_notes.id;


--
-- Name: mentions; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.mentions (
    id integer NOT NULL,
    brand_id integer NOT NULL,
    source_url text NOT NULL,
    source_type text,
    snippet text,
    sentiment text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.mentions OWNER TO agency;

--
-- Name: mentions_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.mentions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.mentions_id_seq OWNER TO agency;

--
-- Name: mentions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.mentions_id_seq OWNED BY public.mentions.id;


--
-- Name: ports; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.ports (
    port integer NOT NULL,
    project_id bigint,
    service text,
    allocated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.ports OWNER TO agency;

--
-- Name: projects; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.projects (
    id bigint NOT NULL,
    name text NOT NULL,
    repo_url text,
    state public.project_state DEFAULT 'idea'::public.project_state NOT NULL,
    prd_path text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.projects OWNER TO agency;

--
-- Name: projects_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.projects_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.projects_id_seq OWNER TO agency;

--
-- Name: projects_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.projects_id_seq OWNED BY public.projects.id;


--
-- Name: resume_versions; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.resume_versions (
    id integer NOT NULL,
    listing_id integer,
    campaign_id integer,
    original_resume text,
    tailored_resume text,
    changes text,
    ats_keywords text[] DEFAULT '{}'::text[],
    status text DEFAULT 'draft'::text,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.resume_versions OWNER TO agency;

--
-- Name: resume_versions_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.resume_versions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.resume_versions_id_seq OWNER TO agency;

--
-- Name: resume_versions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.resume_versions_id_seq OWNED BY public.resume_versions.id;


--
-- Name: services; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.services (
    id bigint NOT NULL,
    project_id bigint,
    name text NOT NULL,
    kind text NOT NULL,
    container text,
    port integer,
    mem_limit_mb integer,
    mem_measured_mb integer,
    status text DEFAULT 'stopped'::text NOT NULL,
    last_seen timestamp with time zone,
    last_good_image text
);


ALTER TABLE public.services OWNER TO agency;

--
-- Name: services_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.services_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.services_id_seq OWNER TO agency;

--
-- Name: services_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.services_id_seq OWNED BY public.services.id;


--
-- Name: suggestions; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.suggestions (
    id integer NOT NULL,
    brand_id integer NOT NULL,
    audit_id integer,
    title text NOT NULL,
    rationale text,
    sources jsonb DEFAULT '[]'::jsonb NOT NULL,
    impact text,
    effort text,
    tier_required text DEFAULT '0'::text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    approval_id integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    rejection_reason text DEFAULT ''::text,
    action_type text DEFAULT 'monitor'::text NOT NULL,
    compliance_flags jsonb DEFAULT '[]'::jsonb NOT NULL
);


ALTER TABLE public.suggestions OWNER TO agency;

--
-- Name: suggestions_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.suggestions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.suggestions_id_seq OWNER TO agency;

--
-- Name: suggestions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.suggestions_id_seq OWNED BY public.suggestions.id;


--
-- Name: tasks; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.tasks (
    id integer NOT NULL,
    type text NOT NULL,
    status text DEFAULT 'queued'::text NOT NULL,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    result_ref text,
    error text,
    prompt_tokens integer DEFAULT 0,
    completion_tokens integer DEFAULT 0,
    cost numeric(12,8) DEFAULT 0,
    triggered_by text DEFAULT 'manual'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone
);


ALTER TABLE public.tasks OWNER TO agency;

--
-- Name: tasks_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.tasks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.tasks_id_seq OWNER TO agency;

--
-- Name: tasks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.tasks_id_seq OWNED BY public.tasks.id;


--
-- Name: token_usage; Type: TABLE; Schema: public; Owner: agency
--

CREATE TABLE public.token_usage (
    id bigint NOT NULL,
    project_id bigint,
    ts timestamp with time zone DEFAULT now() NOT NULL,
    model text,
    tokens_in bigint,
    tokens_out bigint,
    cost_usd numeric(12,6)
);


ALTER TABLE public.token_usage OWNER TO agency;

--
-- Name: token_usage_id_seq; Type: SEQUENCE; Schema: public; Owner: agency
--

CREATE SEQUENCE public.token_usage_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.token_usage_id_seq OWNER TO agency;

--
-- Name: token_usage_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: agency
--

ALTER SEQUENCE public.token_usage_id_seq OWNED BY public.token_usage.id;


--
-- Name: approvals id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.approvals ALTER COLUMN id SET DEFAULT nextval('public.approvals_id_seq'::regclass);


--
-- Name: audits id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.audits ALTER COLUMN id SET DEFAULT nextval('public.audits_id_seq'::regclass);


--
-- Name: background_jobs id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.background_jobs ALTER COLUMN id SET DEFAULT nextval('public.background_jobs_id_seq'::regclass);


--
-- Name: brand_embeddings id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.brand_embeddings ALTER COLUMN id SET DEFAULT nextval('public.brand_embeddings_id_seq'::regclass);


--
-- Name: brand_pipelines id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.brand_pipelines ALTER COLUMN id SET DEFAULT nextval('public.brand_pipelines_id_seq'::regclass);


--
-- Name: brand_properties id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.brand_properties ALTER COLUMN id SET DEFAULT nextval('public.brand_properties_id_seq'::regclass);


--
-- Name: brands id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.brands ALTER COLUMN id SET DEFAULT nextval('public.brands_id_seq'::regclass);


--
-- Name: clients id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.clients ALTER COLUMN id SET DEFAULT nextval('public.clients_id_seq'::regclass);


--
-- Name: competitors id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.competitors ALTER COLUMN id SET DEFAULT nextval('public.competitors_id_seq'::regclass);


--
-- Name: concept_variations id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.concept_variations ALTER COLUMN id SET DEFAULT nextval('public.concept_variations_id_seq'::regclass);


--
-- Name: content_items id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.content_items ALTER COLUMN id SET DEFAULT nextval('public.content_items_id_seq'::regclass);


--
-- Name: cover_letters id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.cover_letters ALTER COLUMN id SET DEFAULT nextval('public.cover_letters_id_seq'::regclass);


--
-- Name: dns_records id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.dns_records ALTER COLUMN id SET DEFAULT nextval('public.dns_records_id_seq'::regclass);


--
-- Name: email_threads id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.email_threads ALTER COLUMN id SET DEFAULT nextval('public.email_threads_id_seq'::regclass);


--
-- Name: health_checks id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.health_checks ALTER COLUMN id SET DEFAULT nextval('public.health_checks_id_seq'::regclass);


--
-- Name: job_applications id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.job_applications ALTER COLUMN id SET DEFAULT nextval('public.job_applications_id_seq'::regclass);


--
-- Name: job_campaigns id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.job_campaigns ALTER COLUMN id SET DEFAULT nextval('public.job_campaigns_id_seq'::regclass);


--
-- Name: job_contacts id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.job_contacts ALTER COLUMN id SET DEFAULT nextval('public.job_contacts_id_seq'::regclass);


--
-- Name: job_listings id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.job_listings ALTER COLUMN id SET DEFAULT nextval('public.job_listings_id_seq'::regclass);


--
-- Name: job_run_history id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.job_run_history ALTER COLUMN id SET DEFAULT nextval('public.job_run_history_id_seq'::regclass);


--
-- Name: job_runs id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.job_runs ALTER COLUMN id SET DEFAULT nextval('public.job_runs_id_seq'::regclass);


--
-- Name: keywords id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.keywords ALTER COLUMN id SET DEFAULT nextval('public.keywords_id_seq'::regclass);


--
-- Name: linkedin_notes id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.linkedin_notes ALTER COLUMN id SET DEFAULT nextval('public.linkedin_notes_id_seq'::regclass);


--
-- Name: mentions id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.mentions ALTER COLUMN id SET DEFAULT nextval('public.mentions_id_seq'::regclass);


--
-- Name: projects id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.projects ALTER COLUMN id SET DEFAULT nextval('public.projects_id_seq'::regclass);


--
-- Name: resume_versions id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.resume_versions ALTER COLUMN id SET DEFAULT nextval('public.resume_versions_id_seq'::regclass);


--
-- Name: services id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.services ALTER COLUMN id SET DEFAULT nextval('public.services_id_seq'::regclass);


--
-- Name: suggestions id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.suggestions ALTER COLUMN id SET DEFAULT nextval('public.suggestions_id_seq'::regclass);


--
-- Name: tasks id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.tasks ALTER COLUMN id SET DEFAULT nextval('public.tasks_id_seq'::regclass);


--
-- Name: token_usage id; Type: DEFAULT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.token_usage ALTER COLUMN id SET DEFAULT nextval('public.token_usage_id_seq'::regclass);


--
-- Name: approvals approvals_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.approvals
    ADD CONSTRAINT approvals_pkey PRIMARY KEY (id);


--
-- Name: audits audits_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.audits
    ADD CONSTRAINT audits_pkey PRIMARY KEY (id);


--
-- Name: background_jobs background_jobs_name_key; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.background_jobs
    ADD CONSTRAINT background_jobs_name_key UNIQUE (name);


--
-- Name: background_jobs background_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.background_jobs
    ADD CONSTRAINT background_jobs_pkey PRIMARY KEY (id);


--
-- Name: brand_embeddings brand_embeddings_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.brand_embeddings
    ADD CONSTRAINT brand_embeddings_pkey PRIMARY KEY (id);


--
-- Name: brand_pipelines brand_pipelines_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.brand_pipelines
    ADD CONSTRAINT brand_pipelines_pkey PRIMARY KEY (id);


--
-- Name: brand_properties brand_properties_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.brand_properties
    ADD CONSTRAINT brand_properties_pkey PRIMARY KEY (id);


--
-- Name: brands brands_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.brands
    ADD CONSTRAINT brands_pkey PRIMARY KEY (id);


--
-- Name: brands brands_slug_key; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.brands
    ADD CONSTRAINT brands_slug_key UNIQUE (slug);


--
-- Name: clients clients_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.clients
    ADD CONSTRAINT clients_pkey PRIMARY KEY (id);


--
-- Name: competitors competitors_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.competitors
    ADD CONSTRAINT competitors_pkey PRIMARY KEY (id);


--
-- Name: concept_variations concept_variations_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.concept_variations
    ADD CONSTRAINT concept_variations_pkey PRIMARY KEY (id);


--
-- Name: content_items content_items_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.content_items
    ADD CONSTRAINT content_items_pkey PRIMARY KEY (id);


--
-- Name: cover_letters cover_letters_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.cover_letters
    ADD CONSTRAINT cover_letters_pkey PRIMARY KEY (id);


--
-- Name: dns_records dns_records_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.dns_records
    ADD CONSTRAINT dns_records_pkey PRIMARY KEY (id);


--
-- Name: dns_records dns_records_subdomain_key; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.dns_records
    ADD CONSTRAINT dns_records_subdomain_key UNIQUE (subdomain);


--
-- Name: email_threads email_threads_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.email_threads
    ADD CONSTRAINT email_threads_pkey PRIMARY KEY (id);


--
-- Name: health_checks health_checks_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.health_checks
    ADD CONSTRAINT health_checks_pkey PRIMARY KEY (id);


--
-- Name: job_applications job_applications_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.job_applications
    ADD CONSTRAINT job_applications_pkey PRIMARY KEY (id);


--
-- Name: job_campaigns job_campaigns_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.job_campaigns
    ADD CONSTRAINT job_campaigns_pkey PRIMARY KEY (id);


--
-- Name: job_contacts job_contacts_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.job_contacts
    ADD CONSTRAINT job_contacts_pkey PRIMARY KEY (id);


--
-- Name: job_listings job_listings_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.job_listings
    ADD CONSTRAINT job_listings_pkey PRIMARY KEY (id);


--
-- Name: job_run_history job_run_history_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.job_run_history
    ADD CONSTRAINT job_run_history_pkey PRIMARY KEY (id);


--
-- Name: job_runs job_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.job_runs
    ADD CONSTRAINT job_runs_pkey PRIMARY KEY (id);


--
-- Name: keywords keywords_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.keywords
    ADD CONSTRAINT keywords_pkey PRIMARY KEY (id);


--
-- Name: linkedin_notes linkedin_notes_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.linkedin_notes
    ADD CONSTRAINT linkedin_notes_pkey PRIMARY KEY (id);


--
-- Name: mentions mentions_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.mentions
    ADD CONSTRAINT mentions_pkey PRIMARY KEY (id);


--
-- Name: ports ports_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.ports
    ADD CONSTRAINT ports_pkey PRIMARY KEY (port);


--
-- Name: projects projects_name_key; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_name_key UNIQUE (name);


--
-- Name: projects projects_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_pkey PRIMARY KEY (id);


--
-- Name: resume_versions resume_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.resume_versions
    ADD CONSTRAINT resume_versions_pkey PRIMARY KEY (id);


--
-- Name: services services_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.services
    ADD CONSTRAINT services_pkey PRIMARY KEY (id);


--
-- Name: services services_project_id_name_key; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.services
    ADD CONSTRAINT services_project_id_name_key UNIQUE (project_id, name);


--
-- Name: suggestions suggestions_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.suggestions
    ADD CONSTRAINT suggestions_pkey PRIMARY KEY (id);


--
-- Name: tasks tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_pkey PRIMARY KEY (id);


--
-- Name: token_usage token_usage_pkey; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.token_usage
    ADD CONSTRAINT token_usage_pkey PRIMARY KEY (id);


--
-- Name: job_applications uq_job_app_listing_campaign; Type: CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.job_applications
    ADD CONSTRAINT uq_job_app_listing_campaign UNIQUE (listing_id, campaign_id);


--
-- Name: idx_email_threads_campaign; Type: INDEX; Schema: public; Owner: agency
--

CREATE INDEX idx_email_threads_campaign ON public.email_threads USING btree (campaign_id);


--
-- Name: idx_job_applications_campaign; Type: INDEX; Schema: public; Owner: agency
--

CREATE INDEX idx_job_applications_campaign ON public.job_applications USING btree (campaign_id);


--
-- Name: idx_job_applications_listing; Type: INDEX; Schema: public; Owner: agency
--

CREATE INDEX idx_job_applications_listing ON public.job_applications USING btree (listing_id);


--
-- Name: idx_job_contacts_listing; Type: INDEX; Schema: public; Owner: agency
--

CREATE INDEX idx_job_contacts_listing ON public.job_contacts USING btree (listing_id);


--
-- Name: idx_job_listings_campaign; Type: INDEX; Schema: public; Owner: agency
--

CREATE INDEX idx_job_listings_campaign ON public.job_listings USING btree (campaign_id);


--
-- Name: idx_job_listings_status; Type: INDEX; Schema: public; Owner: agency
--

CREATE INDEX idx_job_listings_status ON public.job_listings USING btree (status);


--
-- Name: idx_resume_versions_listing; Type: INDEX; Schema: public; Owner: agency
--

CREATE INDEX idx_resume_versions_listing ON public.resume_versions USING btree (listing_id);


--
-- Name: approvals approvals_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.approvals
    ADD CONSTRAINT approvals_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: audits audits_brand_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.audits
    ADD CONSTRAINT audits_brand_id_fkey FOREIGN KEY (brand_id) REFERENCES public.brands(id) ON DELETE CASCADE;


--
-- Name: brand_embeddings brand_embeddings_brand_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.brand_embeddings
    ADD CONSTRAINT brand_embeddings_brand_id_fkey FOREIGN KEY (brand_id) REFERENCES public.brands(id) ON DELETE CASCADE;


--
-- Name: brand_pipelines brand_pipelines_brand_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.brand_pipelines
    ADD CONSTRAINT brand_pipelines_brand_id_fkey FOREIGN KEY (brand_id) REFERENCES public.brands(id) ON DELETE CASCADE;


--
-- Name: brand_properties brand_properties_brand_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.brand_properties
    ADD CONSTRAINT brand_properties_brand_id_fkey FOREIGN KEY (brand_id) REFERENCES public.brands(id) ON DELETE CASCADE;


--
-- Name: clients clients_brand_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.clients
    ADD CONSTRAINT clients_brand_id_fkey FOREIGN KEY (brand_id) REFERENCES public.brands(id) ON DELETE SET NULL;


--
-- Name: clients clients_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.clients
    ADD CONSTRAINT clients_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE SET NULL;


--
-- Name: competitors competitors_brand_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.competitors
    ADD CONSTRAINT competitors_brand_id_fkey FOREIGN KEY (brand_id) REFERENCES public.brands(id) ON DELETE CASCADE;


--
-- Name: concept_variations concept_variations_brand_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.concept_variations
    ADD CONSTRAINT concept_variations_brand_id_fkey FOREIGN KEY (brand_id) REFERENCES public.brands(id) ON DELETE SET NULL;


--
-- Name: concept_variations concept_variations_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.concept_variations
    ADD CONSTRAINT concept_variations_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: concept_variations concept_variations_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.concept_variations
    ADD CONSTRAINT concept_variations_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id);


--
-- Name: content_items content_items_approval_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.content_items
    ADD CONSTRAINT content_items_approval_id_fkey FOREIGN KEY (approval_id) REFERENCES public.approvals(id);


--
-- Name: content_items content_items_brand_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.content_items
    ADD CONSTRAINT content_items_brand_id_fkey FOREIGN KEY (brand_id) REFERENCES public.brands(id) ON DELETE CASCADE;


--
-- Name: content_items content_items_suggestion_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.content_items
    ADD CONSTRAINT content_items_suggestion_id_fkey FOREIGN KEY (suggestion_id) REFERENCES public.suggestions(id);


--
-- Name: content_items content_items_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.content_items
    ADD CONSTRAINT content_items_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id);


--
-- Name: cover_letters cover_letters_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.cover_letters
    ADD CONSTRAINT cover_letters_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.job_campaigns(id) ON DELETE CASCADE;


--
-- Name: cover_letters cover_letters_listing_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.cover_letters
    ADD CONSTRAINT cover_letters_listing_id_fkey FOREIGN KEY (listing_id) REFERENCES public.job_listings(id) ON DELETE CASCADE;


--
-- Name: dns_records dns_records_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.dns_records
    ADD CONSTRAINT dns_records_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: email_threads email_threads_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.email_threads
    ADD CONSTRAINT email_threads_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.job_campaigns(id) ON DELETE CASCADE;


--
-- Name: email_threads email_threads_contact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.email_threads
    ADD CONSTRAINT email_threads_contact_id_fkey FOREIGN KEY (contact_id) REFERENCES public.job_contacts(id) ON DELETE CASCADE;


--
-- Name: email_threads email_threads_listing_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.email_threads
    ADD CONSTRAINT email_threads_listing_id_fkey FOREIGN KEY (listing_id) REFERENCES public.job_listings(id) ON DELETE CASCADE;


--
-- Name: health_checks health_checks_service_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.health_checks
    ADD CONSTRAINT health_checks_service_id_fkey FOREIGN KEY (service_id) REFERENCES public.services(id) ON DELETE CASCADE;


--
-- Name: job_applications job_applications_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.job_applications
    ADD CONSTRAINT job_applications_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.job_campaigns(id) ON DELETE CASCADE;


--
-- Name: job_applications job_applications_contact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.job_applications
    ADD CONSTRAINT job_applications_contact_id_fkey FOREIGN KEY (contact_id) REFERENCES public.job_contacts(id);


--
-- Name: job_applications job_applications_cover_letter_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.job_applications
    ADD CONSTRAINT job_applications_cover_letter_id_fkey FOREIGN KEY (cover_letter_id) REFERENCES public.cover_letters(id);


--
-- Name: job_applications job_applications_listing_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.job_applications
    ADD CONSTRAINT job_applications_listing_id_fkey FOREIGN KEY (listing_id) REFERENCES public.job_listings(id) ON DELETE CASCADE;


--
-- Name: job_applications job_applications_resume_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.job_applications
    ADD CONSTRAINT job_applications_resume_id_fkey FOREIGN KEY (resume_id) REFERENCES public.resume_versions(id);


--
-- Name: job_contacts job_contacts_listing_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.job_contacts
    ADD CONSTRAINT job_contacts_listing_id_fkey FOREIGN KEY (listing_id) REFERENCES public.job_listings(id) ON DELETE CASCADE;


--
-- Name: job_listings job_listings_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.job_listings
    ADD CONSTRAINT job_listings_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.job_campaigns(id) ON DELETE CASCADE;


--
-- Name: job_run_history job_run_history_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.job_run_history
    ADD CONSTRAINT job_run_history_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.job_campaigns(id) ON DELETE CASCADE;


--
-- Name: job_runs job_runs_approval_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.job_runs
    ADD CONSTRAINT job_runs_approval_id_fkey FOREIGN KEY (approval_id) REFERENCES public.approvals(id);


--
-- Name: job_runs job_runs_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.job_runs
    ADD CONSTRAINT job_runs_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.background_jobs(id);


--
-- Name: keywords keywords_brand_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.keywords
    ADD CONSTRAINT keywords_brand_id_fkey FOREIGN KEY (brand_id) REFERENCES public.brands(id) ON DELETE CASCADE;


--
-- Name: linkedin_notes linkedin_notes_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.linkedin_notes
    ADD CONSTRAINT linkedin_notes_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.job_campaigns(id) ON DELETE CASCADE;


--
-- Name: linkedin_notes linkedin_notes_contact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.linkedin_notes
    ADD CONSTRAINT linkedin_notes_contact_id_fkey FOREIGN KEY (contact_id) REFERENCES public.job_contacts(id) ON DELETE CASCADE;


--
-- Name: linkedin_notes linkedin_notes_listing_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.linkedin_notes
    ADD CONSTRAINT linkedin_notes_listing_id_fkey FOREIGN KEY (listing_id) REFERENCES public.job_listings(id) ON DELETE CASCADE;


--
-- Name: mentions mentions_brand_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.mentions
    ADD CONSTRAINT mentions_brand_id_fkey FOREIGN KEY (brand_id) REFERENCES public.brands(id) ON DELETE CASCADE;


--
-- Name: ports ports_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.ports
    ADD CONSTRAINT ports_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: resume_versions resume_versions_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.resume_versions
    ADD CONSTRAINT resume_versions_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.job_campaigns(id) ON DELETE CASCADE;


--
-- Name: resume_versions resume_versions_listing_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.resume_versions
    ADD CONSTRAINT resume_versions_listing_id_fkey FOREIGN KEY (listing_id) REFERENCES public.job_listings(id) ON DELETE CASCADE;


--
-- Name: services services_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.services
    ADD CONSTRAINT services_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: suggestions suggestions_approval_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.suggestions
    ADD CONSTRAINT suggestions_approval_id_fkey FOREIGN KEY (approval_id) REFERENCES public.approvals(id);


--
-- Name: suggestions suggestions_audit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.suggestions
    ADD CONSTRAINT suggestions_audit_id_fkey FOREIGN KEY (audit_id) REFERENCES public.audits(id);


--
-- Name: suggestions suggestions_brand_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.suggestions
    ADD CONSTRAINT suggestions_brand_id_fkey FOREIGN KEY (brand_id) REFERENCES public.brands(id) ON DELETE CASCADE;


--
-- Name: token_usage token_usage_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: agency
--

ALTER TABLE ONLY public.token_usage
    ADD CONSTRAINT token_usage_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- PostgreSQL database dump complete
--

\unrestrict a8Pwe5a8DTpxrNhJzSRStBUuwayOnnV0Zt3GvaI8qYC7CRGfOPjtN7wOupmU9Ke

