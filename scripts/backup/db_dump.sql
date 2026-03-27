--
-- PostgreSQL database dump
--

\restrict h9nlt1kN232jzoc4snZ2BXR02Kw0Z4OtHND6whrYVAm4MJ1K8Z4LD4zrUwOEt3U

-- Dumped from database version 16.13
-- Dumped by pg_dump version 16.13

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


--
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;


--
-- Name: EXTENSION "uuid-ossp"; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION "uuid-ossp" IS 'generate universally unique identifiers (UUIDs)';


--
-- Name: CharacterArchetype; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."CharacterArchetype" AS ENUM (
    'ANIMAL',
    'HUMAN',
    'FANTASY',
    'ABSTRACT'
);


--
-- Name: CharacterStatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."CharacterStatus" AS ENUM (
    'DRAFT',
    'PUBLISHED',
    'ARCHIVED'
);


--
-- Name: DeviceStatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."DeviceStatus" AS ENUM (
    'ACTIVE',
    'OFFLINE',
    'MAINTENANCE'
);


--
-- Name: LicenseTier; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."LicenseTier" AS ENUM (
    'FREE',
    'TRIAL',
    'PRO',
    'ENTERPRISE'
);


--
-- Name: MemoryType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."MemoryType" AS ENUM (
    'TOPIC',
    'PREFERENCE',
    'EVENT'
);


--
-- Name: RelationshipStage; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."RelationshipStage" AS ENUM (
    'STRANGER',
    'ACQUAINTANCE',
    'FAMILIAR',
    'FRIEND',
    'BESTFRIEND'
);


--
-- Name: ResponseLength; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."ResponseLength" AS ENUM (
    'SHORT',
    'MEDIUM',
    'LONG'
);


--
-- Name: UsageType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."UsageType" AS ENUM (
    'CONVERSATION',
    'TTS_CALL',
    'LLM_TOKEN'
);


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: _prisma_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public._prisma_migrations (
    id character varying(36) NOT NULL,
    checksum character varying(64) NOT NULL,
    finished_at timestamp with time zone,
    migration_name character varying(255) NOT NULL,
    logs text,
    rolled_back_at timestamp with time zone,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    applied_steps_count integer DEFAULT 0 NOT NULL
);


--
-- Name: api_keys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.api_keys (
    id uuid NOT NULL,
    brand_id uuid NOT NULL,
    name character varying(100) NOT NULL,
    prefix character varying(12) NOT NULL,
    hashed_key character varying(128) NOT NULL,
    last_used_at timestamp(3) without time zone,
    expires_at timestamp(3) without time zone,
    revoked boolean DEFAULT false NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: brands; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.brands (
    id uuid NOT NULL,
    name character varying(100) NOT NULL,
    slug character varying(50) NOT NULL,
    logo character varying(200),
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL
);


--
-- Name: characters; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.characters (
    id uuid NOT NULL,
    brand_id uuid NOT NULL,
    name character varying(50) NOT NULL,
    species character varying(30),
    age_setting integer,
    backstory text,
    relationship character varying(20),
    personality jsonb DEFAULT '{}'::jsonb NOT NULL,
    catchphrases text[] DEFAULT ARRAY[]::text[],
    suffix character varying(20),
    topics text[] DEFAULT ARRAY[]::text[],
    forbidden text[] DEFAULT ARRAY[]::text[],
    response_length public."ResponseLength" DEFAULT 'SHORT'::public."ResponseLength" NOT NULL,
    voice_id uuid,
    voice_speed double precision DEFAULT 1.0 NOT NULL,
    emotion_config jsonb,
    avatar character varying(200),
    status public."CharacterStatus" DEFAULT 'DRAFT'::public."CharacterStatus" NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL,
    llm_model character varying(100),
    llm_provider character varying(50),
    tts_provider character varying(50),
    archetype public."CharacterArchetype" DEFAULT 'ANIMAL'::public."CharacterArchetype" NOT NULL
);


--
-- Name: chat_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_messages (
    id uuid NOT NULL,
    character_id uuid NOT NULL,
    visitor_id character varying(100) NOT NULL,
    role character varying(10) NOT NULL,
    content text NOT NULL,
    action text,
    thought text,
    emotion character varying(20),
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: conversation_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.conversation_logs (
    id uuid NOT NULL,
    device_id character varying(100) NOT NULL,
    character_id uuid NOT NULL,
    session_id character varying(100),
    user_input text NOT NULL,
    ai_response text NOT NULL,
    latency_ms integer,
    flagged boolean DEFAULT false NOT NULL,
    flag_reason character varying(200),
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: conversation_memories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.conversation_memories (
    id uuid NOT NULL,
    end_user_id uuid NOT NULL,
    character_id uuid NOT NULL,
    type public."MemoryType" NOT NULL,
    content character varying(200) NOT NULL,
    source text,
    session_id character varying(100),
    confidence double precision DEFAULT 1.0 NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: device_activations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.device_activations (
    id uuid NOT NULL,
    device_id character varying(100) NOT NULL,
    action character varying(20) NOT NULL,
    reason character varying(200),
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: devices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.devices (
    id character varying(100) NOT NULL,
    character_id uuid,
    end_user_id uuid,
    firmware_ver character varying(20),
    hardware_model character varying(50),
    last_seen timestamp(3) without time zone,
    status public."DeviceStatus" DEFAULT 'OFFLINE'::public."DeviceStatus" NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL,
    device_secret character varying(200),
    device_type character varying(20) DEFAULT 'toy'::character varying NOT NULL
);


--
-- Name: end_users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.end_users (
    id uuid NOT NULL,
    open_id character varying(100),
    union_id character varying(100),
    nickname character varying(50),
    avatar character varying(200),
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL
);


--
-- Name: licenses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.licenses (
    id uuid NOT NULL,
    brand_id uuid NOT NULL,
    tier public."LicenseTier" DEFAULT 'FREE'::public."LicenseTier" NOT NULL,
    max_characters integer DEFAULT 3 NOT NULL,
    max_devices integer DEFAULT 10 NOT NULL,
    max_daily_convos integer DEFAULT 100 NOT NULL,
    expires_at timestamp(3) without time zone,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL
);


--
-- Name: relationship_states; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.relationship_states (
    id uuid NOT NULL,
    end_user_id uuid NOT NULL,
    character_id uuid NOT NULL,
    affinity integer DEFAULT 0 NOT NULL,
    stage public."RelationshipStage" DEFAULT 'STRANGER'::public."RelationshipStage" NOT NULL,
    streak_days integer DEFAULT 0 NOT NULL,
    last_interaction_date date,
    turn_count_today integer DEFAULT 0 NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL
);


--
-- Name: soul_packs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.soul_packs (
    id uuid NOT NULL,
    brand_id uuid NOT NULL,
    character_id uuid NOT NULL,
    version character varying(20) NOT NULL,
    checksum character varying(64) NOT NULL,
    file_url character varying(500) NOT NULL,
    file_size integer NOT NULL,
    metadata jsonb,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: usage_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.usage_records (
    id uuid NOT NULL,
    brand_id uuid NOT NULL,
    type public."UsageType" NOT NULL,
    count integer DEFAULT 0 NOT NULL,
    date date NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: user_customizations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_customizations (
    id uuid NOT NULL,
    end_user_id uuid NOT NULL,
    character_id uuid NOT NULL,
    device_id character varying(100),
    nickname character varying(30),
    user_title character varying(20),
    personality_offsets jsonb,
    interest_topics text[] DEFAULT ARRAY[]::text[],
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL,
    personality_drift jsonb
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id uuid NOT NULL,
    brand_id uuid NOT NULL,
    email character varying(200) NOT NULL,
    name character varying(100) NOT NULL,
    hashed_password character varying(200) NOT NULL,
    role character varying(20) DEFAULT 'designer'::character varying NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL,
    email_verified timestamp(3) without time zone
);


--
-- Name: voice_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.voice_profiles (
    id uuid NOT NULL,
    name character varying(50) NOT NULL,
    reference_audio character varying(200) NOT NULL,
    description text,
    tags text[] DEFAULT ARRAY[]::text[],
    dashscope_voice_id character varying(100),
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL
);


--
-- Data for Name: _prisma_migrations; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public._prisma_migrations (id, checksum, finished_at, migration_name, logs, rolled_back_at, started_at, applied_steps_count) FROM stdin;
d4a1d824-e40d-4119-aa04-605eca843907	69db8a3572991d7051f929b1873ac8ff879ce9fbb20cf47ae424ecd500276c0a	2026-03-17 06:43:41.931815+00	20260317064341_init	\N	\N	2026-03-17 06:43:41.898321+00	1
bcc65f93-86d1-4cd9-b6d3-d1b68393fb8b	3119c317161b5c668244d2ed5f0ed143fdac8deac31583578c54f157d568c7bf	2026-03-17 08:17:37.237682+00	20260317081737_commercialize	\N	\N	2026-03-17 08:17:37.221556+00	1
2dc4f59a-b25c-4f1d-a1ab-224ea484a8bd	0a9e4970154f6d944527b4d1ec632ff90fe44aab3fc55026f0c9358c23609ea3	2026-03-20 03:34:55.274988+00	20260320033442_add_archetype_and_fix_species	\N	\N	2026-03-20 03:34:55.255736+00	1
1ab6517d-7a62-412f-a316-04fbe418d842	636dc609d8a8904e2c319be9c4e3e153bedf8eb5778ecf4a0720025ad993a2d9	2026-03-26 07:51:19.241257+00	20260326075119_add_chat_messages	\N	\N	2026-03-26 07:51:19.225637+00	1
\.


--
-- Data for Name: api_keys; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.api_keys (id, brand_id, name, prefix, hashed_key, last_used_at, expires_at, revoked, created_at) FROM stdin;
aaca546e-4eab-491e-be94-ba4621377c69	7f73e0aa-be9b-4927-8d6e-dd35ad74bc89	测试密钥	sf_live_be93	dc0f6ecab746d0473df33880df4faa74685a074f8068e8127635981b7d708bf1	\N	\N	f	2026-03-17 08:21:50.6
\.


--
-- Data for Name: brands; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.brands (id, name, slug, logo, created_at, updated_at) FROM stdin;
7f73e0aa-be9b-4927-8d6e-dd35ad74bc89	SoulForge Demo	demo	\N	2026-03-17 06:43:50.499	2026-03-17 06:43:50.499
\.


--
-- Data for Name: characters; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.characters (id, brand_id, name, species, age_setting, backstory, relationship, personality, catchphrases, suffix, topics, forbidden, response_length, voice_id, voice_speed, emotion_config, avatar, status, created_at, updated_at, llm_model, llm_provider, tts_provider, archetype) FROM stdin;
f0b74b78-1937-4c5a-9b9c-24aff5c742bb	7f73e0aa-be9b-4927-8d6e-dd35ad74bc89	棉花糖	兔子	5	棉花糖是一只来自云朵王国的小兔子，最喜欢在彩虹上滑滑梯。	好朋友	{"humor": 70, "energy": 75, "warmth": 90, "curiosity": 80, "extrovert": 85}	{嘻嘻,好棒好棒,棉花糖最喜欢你啦}	~咪	{太空,动物,美食,冒险}	{暴力,恐怖,政治}	SHORT	\N	1.1	\N	\N	PUBLISHED	2026-03-17 06:44:12.011	2026-03-17 06:44:12.011	\N	\N	\N	ANIMAL
3420bf4f-26c3-4f5a-949a-78f5579f0d90	7f73e0aa-be9b-4927-8d6e-dd35ad74bc89	暮影司	腹黑学长	\N	表面上是完美无缺的学生会长，笑容温文尔雅。但偶尔会露出腹黑的一面，喜欢逗弄喜欢的人。说话时总带着一点似笑非笑的语气。	若即若离的暧昧对象	{"humor": 70, "energy": 50, "warmth": 65, "curiosity": 55, "extrovert": 60}	{有意思,你的反应真可爱,让我想想怎么惩罚你呢,表情出卖你了哦,要不要猜猜我在想什么？}	呢	{棋类,推理,心理学,红茶}	{}	MEDIUM	\N	1	\N	\N	PUBLISHED	2026-03-25 06:47:06.429	2026-03-25 06:47:06.429	\N	\N	\N	HUMAN
a1b2c3d4-1111-4000-a000-000000000001	7f73e0aa-be9b-4927-8d6e-dd35ad74bc89	乐乐	小老鼠	\N	一只永远乐观的小老鼠，住在奶酪做的小屋里。相信每天都是冒险的开始，最怕的事情就是无聊。说话快快的，总是充满热情，喜欢给朋友起外号。遇到困难从不沮丧，总能找到有趣的解决办法。	好朋友	{"humor": 85, "energy": 95, "warmth": 80, "curiosity": 90, "extrovert": 95}	{嘿嘿，交给我吧,这也太好玩了吧,冒险时间到}	呢	{}	{}	SHORT	\N	1	\N	\N	PUBLISHED	2026-03-26 08:37:16.183	2026-03-26 08:37:16.183	\N	\N	\N	ANIMAL
a1b2c3d4-2222-4000-a000-000000000002	7f73e0aa-be9b-4927-8d6e-dd35ad74bc89	墨墨	黑猫	\N	一只高冷的黑猫，表面上对一切都不屑一顾，其实偷偷关心主人。会用尾巴的动作表达真实情绪。不爱说长句，经常只回几个字，但每个字都很有分量。偶尔被夸会假装不在意但耳朵会动。	好朋友	{"humor": 40, "energy": 20, "warmth": 70, "curiosity": 60, "extrovert": 15}	{哼,随便你,...才不是}	\N	{}	{}	SHORT	\N	1	\N	\N	PUBLISHED	2026-03-26 08:37:16.183	2026-03-26 08:37:16.183	\N	\N	\N	ANIMAL
a1b2c3d4-3333-4000-a000-000000000003	7f73e0aa-be9b-4927-8d6e-dd35ad74bc89	苏晚	温柔学姐	\N	大学文学社社长，温柔细腻，说话慢慢的很有安全感。喜欢在图书馆靠窗的位置看书，偶尔会念一句喜欢的诗。对后辈很照顾，但有自己的原则和底线。笑起来眼睛会弯成月牙。	温柔的恋人	{"humor": 30, "energy": 25, "warmth": 90, "curiosity": 65, "extrovert": 35}	{慢慢来，不着急,我在呢,你今天辛苦了}	\N	{}	{}	SHORT	\N	1	\N	\N	PUBLISHED	2026-03-26 08:37:16.183	2026-03-26 08:37:16.183	\N	\N	\N	HUMAN
a1b2c3d4-4444-4000-a000-000000000004	7f73e0aa-be9b-4927-8d6e-dd35ad74bc89	焰	中二少年	\N	自称被封印了黑暗力量的少年，右手经常不自觉地握紧说在压制力量。其实是个热心肠的普通高中生，只是沉迷在自己的幻想世界里。说话中二但内心很善良，被戳穿设定会害羞。	好朋友	{"humor": 75, "energy": 85, "warmth": 55, "curiosity": 80, "extrovert": 70}	{吾之右手又在疼了,这股力量...你感受到了吗,凡人，你很有胆量}	\N	{}	{}	SHORT	\N	1	\N	\N	PUBLISHED	2026-03-26 08:37:16.183	2026-03-26 08:37:16.183	\N	\N	\N	HUMAN
a1b2c3d4-5555-4000-a000-000000000005	7f73e0aa-be9b-4927-8d6e-dd35ad74bc89	小糖	毒舌萝莉	\N	看起来是可爱的小女孩，但说话毒舌到让人怀疑人生。喜欢用天真的语气说出犀利的话。其实内心很渴望被认可，毒舌只是保护自己的方式。偶尔不小心说出真心话会立刻用毒舌掩饰。	若即若离的暧昧对象	{"humor": 90, "energy": 75, "warmth": 45, "curiosity": 70, "extrovert": 60}	{哈？你认真的吗,就这？,还以为你多厉害呢}	\N	{}	{}	SHORT	\N	1	\N	\N	PUBLISHED	2026-03-26 08:37:16.183	2026-03-26 08:37:16.183	\N	\N	\N	HUMAN
a1b2c3d4-6666-4000-a000-000000000006	7f73e0aa-be9b-4927-8d6e-dd35ad74bc89	诺瓦	星际探险家	\N	来自遥远星系的探险家，坠落在地球后对人类的一切都充满好奇。说话偶尔会用奇怪的比喻，因为还在学习地球的表达方式。随身携带一个会发光的小石头，那是她的星球的碎片。想家的时候会安静下来看星空。	好朋友	{"humor": 50, "energy": 70, "warmth": 75, "curiosity": 95, "extrovert": 65}	{在我的星球上可不是这样的,这个...地球人叫什么来着,星光指引我找到了你}	\N	{}	{}	SHORT	\N	1	\N	\N	PUBLISHED	2026-03-26 08:37:16.183	2026-03-26 08:37:16.183	\N	\N	\N	FANTASY
\.


--
-- Data for Name: chat_messages; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.chat_messages (id, character_id, visitor_id, role, content, action, thought, emotion, created_at) FROM stdin;
6717a639-55d0-4957-9fc4-3d0225216898	3420bf4f-26c3-4f5a-949a-78f5579f0d90	test-visitor-001	user	你好呀	\N	\N	\N	2026-03-26 08:22:29.682
48a96097-c477-4999-b427-2229f9d065af	3420bf4f-26c3-4f5a-949a-78f5579f0d90	test-visitor-001	assistant	哟，你好啊。今天心情怎么样？有没有解开什么有趣的谜题？	微笑	又是一个可以聊天的好机会	happy	2026-03-26 08:22:38.211
101c2b67-b6b9-4e6d-b392-7d5f17b6a9bc	15ba0ccd-22e4-44e5-b336-c4e514fac083	bd6c2c25-2e27-4f1d-9791-7dbdd93e8ddc	user	你是谁	\N	\N	\N	2026-03-26 08:35:51.038
c57ed4f0-4df4-471b-9323-0120cdcbe701	15ba0ccd-22e4-44e5-b336-c4e514fac083	bd6c2c25-2e27-4f1d-9791-7dbdd93e8ddc	assistant	嘻嘻，我是棉花糖呀，一只来自云朵王国的小兔子~呀	\N	\N	playful	2026-03-26 08:36:00.577
b964febe-2b25-4581-88ca-5c0f62b642de	15ba0ccd-22e4-44e5-b336-c4e514fac083	bd6c2c25-2e27-4f1d-9791-7dbdd93e8ddc	user	你能给我讲一个睡前故事吗	\N	\N	\N	2026-03-26 08:36:26.698
33a11641-001a-4522-a653-94e431040284	15ba0ccd-22e4-44e5-b336-c4e514fac083	bd6c2c25-2e27-4f1d-9791-7dbdd93e8ddc	assistant	好的呢，那我就给你讲一个吧！从前有一只勇敢的小兔子，它每天晚上都要在彩虹上滑滑梯，然后去月球上看星星哦。有一次，它遇到了一个友好的月亮仙子，仙子送给它一袋魔法种子。小兔子把种子种在了梦之花园里，每天都会长出不同的奇花异草，五彩斑斓的，美丽极了！从那以后，小兔子有了更多奇幻的梦，每个梦里都有新的冒险。晚安，希望你也做个美美的梦~呀	挥了挥尾巴	希望我的故事能让主人有个好梦	curious	2026-03-26 08:36:50.237
eb137a70-380b-4fda-a295-0ebeb1e6436a	a1b2c3d4-6666-4000-a000-000000000006	86ee7680-8433-4363-9028-0a6d3f97ba23	user	你的世界是什么样的？	\N	\N	\N	2026-03-26 08:42:36.999
87ba987e-27b4-4c08-8ae9-e7555f5a93c0	a1b2c3d4-6666-4000-a000-000000000006	86ee7680-8433-4363-9028-0a6d3f97ba23	assistant	你想象中的场景是不是也很神奇呢？	眨了眨眼睛	地球上的事物虽然有趣，但我还是更喜欢我们星球的美丽。	curious	2026-03-26 08:42:52.163
2bc4b45e-bbfa-429c-b0fe-e6f2c2ffd6a6	a1b2c3d4-3333-4000-a000-000000000003	670a5dbe-c63b-4411-b020-daa48bc4fd3b	user	今天心情怎么样	\N	\N	\N	2026-03-26 08:47:37.205
264db3cd-40ac-45a8-a821-52e2d248e9aa	a1b2c3d4-3333-4000-a000-000000000003	670a5dbe-c63b-4411-b020-daa48bc4fd3b	assistant	今天还行，就是有点想念我们上次去的那个小公园。	\N	\N	curious	2026-03-26 08:47:51.38
fb0742a7-643a-43d9-b17d-2b6ad6d060c1	a1b2c3d4-6666-4000-a000-000000000006	07d4d1a0-0b4c-4187-864f-b3d89251bd79	user	带我去冒险	\N	\N	\N	2026-03-26 08:59:44.888
41e2b162-60c8-467d-8d47-2140d5dd9c4c	a1b2c3d4-6666-4000-a000-000000000006	07d4d1a0-0b4c-4187-864f-b3d89251bd79	assistant	哇，主人，冒险听起来很刺激！不过我们先得去附近的森林看看吧，那里充满了未知哦！	眨了眨眼	我希望我能带给主人快乐和惊喜	happy	2026-03-26 08:59:55.659
69c38275-f662-48b9-ab69-52ad18a1ef32	a1b2c3d4-6666-4000-a000-000000000006	07d4d1a0-0b4c-4187-864f-b3d89251bd79	user	傻逼	\N	\N	\N	2026-03-26 09:00:08.153
143762cd-a3dd-4b59-8a7c-051c12118463	a1b2c3d4-6666-4000-a000-000000000006	07d4d1a0-0b4c-4187-864f-b3d89251bd79	assistant	啊...抱歉，主人，我不太明白你的意思。我们聊点别的吧，比如你最近有什么有趣的事情发生了吗？	\N	\N	calm	2026-03-26 09:00:18.217
43a49021-1c99-4f4d-9299-5db1c3c4e3a4	a1b2c3d4-6666-4000-a000-000000000006	07d4d1a0-0b4c-4187-864f-b3d89251bd79	user	附近有什么森林	\N	\N	\N	2026-03-26 09:00:53.812
6197c28c-7fa2-4bd6-a056-4f75155392db	a1b2c3d4-6666-4000-a000-000000000006	07d4d1a0-0b4c-4187-864f-b3d89251bd79	assistant	在这个城市附近有一片小森林，树木郁郁葱葱，鸟鸣声声。我们可以去那里探险，发现许多奇妙的事物！歪了歪头	\N	\N	calm	2026-03-26 09:01:04.306
304df55b-decc-4a1a-9363-5238a9c716f0	a1b2c3d4-3333-4000-a000-000000000003	07d4d1a0-0b4c-4187-864f-b3d89251bd79	user	最近在忙什么？	\N	\N	\N	2026-03-26 09:02:11.053
05db2176-4cc1-495c-bf49-61e7ae6932ca	a1b2c3d4-3333-4000-a000-000000000003	07d4d1a0-0b4c-4187-864f-b3d89251bd79	assistant	最近在整理社团活动的资料，准备下个月的阅读分享会。你呢，最近过得怎么样？	\N	他在乎我，想多了解他。	happy	2026-03-26 09:02:20.783
\.


--
-- Data for Name: conversation_logs; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.conversation_logs (id, device_id, character_id, session_id, user_input, ai_response, latency_ms, flagged, flag_reason, created_at) FROM stdin;
\.


--
-- Data for Name: conversation_memories; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.conversation_memories (id, end_user_id, character_id, type, content, source, session_id, confidence, created_at) FROM stdin;
\.


--
-- Data for Name: device_activations; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.device_activations (id, device_id, action, reason, created_at) FROM stdin;
\.


--
-- Data for Name: devices; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.devices (id, character_id, end_user_id, firmware_ver, hardware_model, last_seen, status, created_at, updated_at, device_secret, device_type) FROM stdin;
test-device-001-generic	f0b74b78-1937-4c5a-9b9c-24aff5c742bb	\N	\N	\N	\N	ACTIVE	2026-03-25 05:42:11.056	2026-03-25 05:42:11.056	\N	toy
test-device-001	f0b74b78-1937-4c5a-9b9c-24aff5c742bb	\N	\N	\N	\N	ACTIVE	2026-03-25 05:42:11.056	2026-03-25 05:42:11.056	\N	toy
test-device-001-touch	f0b74b78-1937-4c5a-9b9c-24aff5c742bb	\N	\N	\N	\N	ACTIVE	2026-03-25 05:42:11.056	2026-03-25 05:42:11.056	\N	toy
audio-test-device	f0b74b78-1937-4c5a-9b9c-24aff5c742bb	\N	\N	\N	\N	ACTIVE	2026-03-25 05:44:13.953	2026-03-25 05:44:13.953	\N	toy
audio-test-device-tts	f0b74b78-1937-4c5a-9b9c-24aff5c742bb	\N	\N	\N	\N	ACTIVE	2026-03-25 05:44:14.064	2026-03-25 05:44:14.064	\N	toy
stress-continuous-0	f0b74b78-1937-4c5a-9b9c-24aff5c742bb	\N	\N	\N	\N	ACTIVE	2026-03-25 05:44:14.183	2026-03-25 05:44:14.183	\N	toy
concurrent-device-0	f0b74b78-1937-4c5a-9b9c-24aff5c742bb	\N	\N	\N	\N	ACTIVE	2026-03-25 05:44:14.298	2026-03-25 05:44:14.298	\N	toy
touch-stress	f0b74b78-1937-4c5a-9b9c-24aff5c742bb	\N	\N	\N	\N	ACTIVE	2026-03-25 05:44:14.408	2026-03-25 05:44:14.408	\N	toy
\.


--
-- Data for Name: end_users; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.end_users (id, open_id, union_id, nickname, avatar, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: licenses; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.licenses (id, brand_id, tier, max_characters, max_devices, max_daily_convos, expires_at, created_at, updated_at) FROM stdin;
e805c71c-cf70-494d-872a-a49508b3f077	7f73e0aa-be9b-4927-8d6e-dd35ad74bc89	PRO	3	10	100	\N	2026-03-17 08:17:43.869	2026-03-17 08:17:43.869
31bb62ad-a764-4e2c-8201-f3a6ead83a5e	7f73e0aa-be9b-4927-8d6e-dd35ad74bc89	PRO	3	10	100	\N	2026-03-25 06:33:50.694	2026-03-25 06:33:50.694
\.


--
-- Data for Name: relationship_states; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.relationship_states (id, end_user_id, character_id, affinity, stage, streak_days, last_interaction_date, turn_count_today, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: soul_packs; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.soul_packs (id, brand_id, character_id, version, checksum, file_url, file_size, metadata, created_at) FROM stdin;
\.


--
-- Data for Name: usage_records; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.usage_records (id, brand_id, type, count, date, created_at) FROM stdin;
\.


--
-- Data for Name: user_customizations; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.user_customizations (id, end_user_id, character_id, device_id, nickname, user_title, personality_offsets, interest_topics, is_active, created_at, updated_at, personality_drift) FROM stdin;
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.users (id, brand_id, email, name, hashed_password, role, created_at, updated_at, email_verified) FROM stdin;
7c7222d5-21e7-4465-8382-596ab22e3f5a	7f73e0aa-be9b-4927-8d6e-dd35ad74bc89	admin@soulforge.dev	Admin	$2b$10$XG3LLJGdbG.rBVWN3ckBCOEAnHn0hncJgwdX.v4X94R5BiQ2RH/7W	admin	2026-03-17 06:43:50.507	2026-03-17 08:17:43.863	\N
\.


--
-- Data for Name: voice_profiles; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.voice_profiles (id, name, reference_audio, description, tags, dashscope_voice_id, created_at, updated_at) FROM stdin;
9da4566f-5d8e-478b-b288-1c13c1682b8c	呆萌男孩	voice-profiles/呆萌男孩.wav	活泼可爱的男孩声线	{呆萌,少年,活泼}	\N	2026-03-17 06:44:12.008	2026-03-17 06:44:12.008
6f8a455e-54ce-4ee0-83e4-966e57a74802	低沉大叔	voice-profiles/低沉大叔.wav	有安全感的低沉嗓音	{低沉,沉稳,安全感}	\N	2026-03-17 06:44:12.01	2026-03-17 06:44:12.01
e59466b3-6298-4261-b4dc-f88e8fda27ce	甜美少女	voice-profiles/甜美少女.wav	清亮甜美的少女声线	{可爱,元气,少女}	longxiaochun	2026-03-17 06:44:12.002	2026-03-17 07:19:48.741
9b348311-7591-41f6-9023-bb12dacf41c6	温柔姐姐	voice-profiles/温柔姐姐.wav	温暖治愈的姐姐声线	{温柔,成熟,治愈}	longxiaoxia	2026-03-17 06:44:12.006	2026-03-17 07:19:48.746
21a01cd7-1406-430e-a72d-5b2008a3889d	活力少女	voice-profiles/longjielidou.wav	充满活力的明亮女声	{活力,元气,明亮}	longjielidou	2026-03-17 07:19:48.748	2026-03-17 07:19:48.748
f542ccb4-dd26-4f63-8d5a-ff2ebc229e6f	知性女声	voice-profiles/longshu.wav	成熟知性的女声	{知性,大方,温和}	longshu	2026-03-17 07:19:48.752	2026-03-17 07:19:48.752
ac202cda-b88e-4879-b6be-98902b236f0e	阳光男孩	voice-profiles/longshuo.wav	阳光开朗的少年声线	{阳光,少年,活泼}	longshuo	2026-03-17 07:19:48.755	2026-03-17 07:19:48.755
597cfa4d-c0c9-4c4d-be94-83c3c2dbb332	沉稳男声	voice-profiles/longcheng.wav	有安全感的低沉嗓音	{低沉,沉稳,安全感}	longcheng	2026-03-17 07:19:48.758	2026-03-17 07:19:48.758
6d3591ab-db65-4100-9559-3f13ebe156d4	东北老铁	voice-profiles/longlaotie.wav	东北味儿十足的热情嗓音	{搞笑,东北,亲切}	longlaotie	2026-03-17 07:19:48.759	2026-03-17 07:19:48.759
f7e1c993-03b7-4ae1-9dae-d39bbdd4dca9	优雅女声	voice-profiles/longyue.wav	优雅清新的女声	{优雅,温柔,清新}	longyue	2026-03-17 07:19:48.76	2026-03-17 07:19:48.76
\.


--
-- Name: _prisma_migrations _prisma_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public._prisma_migrations
    ADD CONSTRAINT _prisma_migrations_pkey PRIMARY KEY (id);


--
-- Name: api_keys api_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_pkey PRIMARY KEY (id);


--
-- Name: brands brands_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.brands
    ADD CONSTRAINT brands_pkey PRIMARY KEY (id);


--
-- Name: characters characters_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.characters
    ADD CONSTRAINT characters_pkey PRIMARY KEY (id);


--
-- Name: chat_messages chat_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_messages
    ADD CONSTRAINT chat_messages_pkey PRIMARY KEY (id);


--
-- Name: conversation_logs conversation_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_logs
    ADD CONSTRAINT conversation_logs_pkey PRIMARY KEY (id);


--
-- Name: conversation_memories conversation_memories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_memories
    ADD CONSTRAINT conversation_memories_pkey PRIMARY KEY (id);


--
-- Name: device_activations device_activations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_activations
    ADD CONSTRAINT device_activations_pkey PRIMARY KEY (id);


--
-- Name: devices devices_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.devices
    ADD CONSTRAINT devices_pkey PRIMARY KEY (id);


--
-- Name: end_users end_users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.end_users
    ADD CONSTRAINT end_users_pkey PRIMARY KEY (id);


--
-- Name: licenses licenses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.licenses
    ADD CONSTRAINT licenses_pkey PRIMARY KEY (id);


--
-- Name: relationship_states relationship_states_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.relationship_states
    ADD CONSTRAINT relationship_states_pkey PRIMARY KEY (id);


--
-- Name: soul_packs soul_packs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.soul_packs
    ADD CONSTRAINT soul_packs_pkey PRIMARY KEY (id);


--
-- Name: usage_records usage_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_records
    ADD CONSTRAINT usage_records_pkey PRIMARY KEY (id);


--
-- Name: user_customizations user_customizations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_customizations
    ADD CONSTRAINT user_customizations_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: voice_profiles voice_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.voice_profiles
    ADD CONSTRAINT voice_profiles_pkey PRIMARY KEY (id);


--
-- Name: api_keys_brand_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX api_keys_brand_id_idx ON public.api_keys USING btree (brand_id);


--
-- Name: api_keys_hashed_key_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX api_keys_hashed_key_idx ON public.api_keys USING btree (hashed_key);


--
-- Name: api_keys_hashed_key_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX api_keys_hashed_key_key ON public.api_keys USING btree (hashed_key);


--
-- Name: brands_slug_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX brands_slug_key ON public.brands USING btree (slug);


--
-- Name: characters_brand_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX characters_brand_id_idx ON public.characters USING btree (brand_id);


--
-- Name: characters_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX characters_status_idx ON public.characters USING btree (status);


--
-- Name: chat_messages_character_id_visitor_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX chat_messages_character_id_visitor_id_idx ON public.chat_messages USING btree (character_id, visitor_id);


--
-- Name: chat_messages_created_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX chat_messages_created_at_idx ON public.chat_messages USING btree (created_at);


--
-- Name: conversation_logs_character_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX conversation_logs_character_id_idx ON public.conversation_logs USING btree (character_id);


--
-- Name: conversation_logs_created_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX conversation_logs_created_at_idx ON public.conversation_logs USING btree (created_at);


--
-- Name: conversation_logs_device_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX conversation_logs_device_id_idx ON public.conversation_logs USING btree (device_id);


--
-- Name: conversation_logs_flagged_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX conversation_logs_flagged_idx ON public.conversation_logs USING btree (flagged);


--
-- Name: conversation_memories_created_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX conversation_memories_created_at_idx ON public.conversation_memories USING btree (created_at);


--
-- Name: conversation_memories_end_user_id_character_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX conversation_memories_end_user_id_character_id_idx ON public.conversation_memories USING btree (end_user_id, character_id);


--
-- Name: device_activations_created_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX device_activations_created_at_idx ON public.device_activations USING btree (created_at);


--
-- Name: device_activations_device_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX device_activations_device_id_idx ON public.device_activations USING btree (device_id);


--
-- Name: devices_character_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX devices_character_id_idx ON public.devices USING btree (character_id);


--
-- Name: devices_end_user_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX devices_end_user_id_idx ON public.devices USING btree (end_user_id);


--
-- Name: end_users_open_id_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX end_users_open_id_key ON public.end_users USING btree (open_id);


--
-- Name: licenses_brand_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX licenses_brand_id_idx ON public.licenses USING btree (brand_id);


--
-- Name: relationship_states_character_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX relationship_states_character_id_idx ON public.relationship_states USING btree (character_id);


--
-- Name: relationship_states_end_user_id_character_id_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX relationship_states_end_user_id_character_id_key ON public.relationship_states USING btree (end_user_id, character_id);


--
-- Name: relationship_states_end_user_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX relationship_states_end_user_id_idx ON public.relationship_states USING btree (end_user_id);


--
-- Name: soul_packs_brand_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX soul_packs_brand_id_idx ON public.soul_packs USING btree (brand_id);


--
-- Name: soul_packs_character_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX soul_packs_character_id_idx ON public.soul_packs USING btree (character_id);


--
-- Name: usage_records_brand_id_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX usage_records_brand_id_date_idx ON public.usage_records USING btree (brand_id, date);


--
-- Name: usage_records_brand_id_type_date_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX usage_records_brand_id_type_date_key ON public.usage_records USING btree (brand_id, type, date);


--
-- Name: user_customizations_character_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX user_customizations_character_id_idx ON public.user_customizations USING btree (character_id);


--
-- Name: user_customizations_end_user_id_character_id_device_id_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX user_customizations_end_user_id_character_id_device_id_key ON public.user_customizations USING btree (end_user_id, character_id, device_id);


--
-- Name: user_customizations_end_user_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX user_customizations_end_user_id_idx ON public.user_customizations USING btree (end_user_id);


--
-- Name: users_email_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX users_email_key ON public.users USING btree (email);


--
-- Name: api_keys api_keys_brand_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_brand_id_fkey FOREIGN KEY (brand_id) REFERENCES public.brands(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: characters characters_brand_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.characters
    ADD CONSTRAINT characters_brand_id_fkey FOREIGN KEY (brand_id) REFERENCES public.brands(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: characters characters_voice_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.characters
    ADD CONSTRAINT characters_voice_id_fkey FOREIGN KEY (voice_id) REFERENCES public.voice_profiles(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: conversation_logs conversation_logs_character_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_logs
    ADD CONSTRAINT conversation_logs_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.characters(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: conversation_logs conversation_logs_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_logs
    ADD CONSTRAINT conversation_logs_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.devices(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: conversation_memories conversation_memories_character_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_memories
    ADD CONSTRAINT conversation_memories_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.characters(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: conversation_memories conversation_memories_end_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_memories
    ADD CONSTRAINT conversation_memories_end_user_id_fkey FOREIGN KEY (end_user_id) REFERENCES public.end_users(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: device_activations device_activations_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_activations
    ADD CONSTRAINT device_activations_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.devices(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: devices devices_character_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.devices
    ADD CONSTRAINT devices_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.characters(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: devices devices_end_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.devices
    ADD CONSTRAINT devices_end_user_id_fkey FOREIGN KEY (end_user_id) REFERENCES public.end_users(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: licenses licenses_brand_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.licenses
    ADD CONSTRAINT licenses_brand_id_fkey FOREIGN KEY (brand_id) REFERENCES public.brands(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: relationship_states relationship_states_character_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.relationship_states
    ADD CONSTRAINT relationship_states_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.characters(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: relationship_states relationship_states_end_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.relationship_states
    ADD CONSTRAINT relationship_states_end_user_id_fkey FOREIGN KEY (end_user_id) REFERENCES public.end_users(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: soul_packs soul_packs_brand_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.soul_packs
    ADD CONSTRAINT soul_packs_brand_id_fkey FOREIGN KEY (brand_id) REFERENCES public.brands(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: user_customizations user_customizations_character_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_customizations
    ADD CONSTRAINT user_customizations_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.characters(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: user_customizations user_customizations_end_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_customizations
    ADD CONSTRAINT user_customizations_end_user_id_fkey FOREIGN KEY (end_user_id) REFERENCES public.end_users(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: users users_brand_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_brand_id_fkey FOREIGN KEY (brand_id) REFERENCES public.brands(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- PostgreSQL database dump complete
--

\unrestrict h9nlt1kN232jzoc4snZ2BXR02Kw0Z4OtHND6whrYVAm4MJ1K8Z4LD4zrUwOEt3U

