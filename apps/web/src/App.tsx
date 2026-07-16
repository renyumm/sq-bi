import React, { Suspense, lazy, useCallback, useState, useEffect, useRef } from 'react';
import {
  Database,
  MessageSquare,
  TrendingUp,
  Settings,
  RefreshCw,
  AlertTriangle,
  Plus,
  Trash2,
  X,
  Package
} from 'lucide-react';
import { api } from './api';
import type {
  DataSource,
  Lineage,
  LlmSettings,
  MetricDependencyRecord,
  MetricDefinition,
  SemanticField,
  SkillDefinition,
  UserContext,
  ManagedUser,
  ReportDefinition,
  SaveExplorationAsMetricRequest,
  EnterprisePack,
  ChatSessionRecord,
  CallableAsset
} from './api';

// Subcomponents
import { ManagementPage, ModalFrame, ActionButton } from './components/ui/ManagementUI';
import { confirmAction, registerSystemConfirm } from './systemDialog';

const PackDeploymentWorkbench = lazy(() => import('./components/PackDeploymentWorkbench').then(module => ({ default: module.PackDeploymentWorkbench })));
const AskDashboard = lazy(() => import('./components/AskDashboard').then(module => ({ default: module.AskDashboard })));
const PackProducts = lazy(() => import('./components/PackProducts').then(module => ({ default: module.PackProducts })));
const PackEditor = lazy(() => import('./components/PackEditor').then(module => ({ default: module.PackEditor })));
const AssetWorkspace = lazy(() => import('./components/AssetWorkspace').then(module => ({ default: module.AssetWorkspace })));
const DataSourceManager = lazy(() => import('./components/DataSourceManager').then(module => ({ default: module.DataSourceManager })));
const SemanticProfileViewer = lazy(() => import('./components/SemanticProfileViewer').then(module => ({ default: module.SemanticProfileViewer })));
const SystemSettingsPage = lazy(() => import('./components/SystemSettingsPage').then(module => ({ default: module.SystemSettingsPage })));

function getErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error) {
    return err.message;
  }
  if (typeof err === 'object' && err !== null && 'message' in err && typeof err.message === 'string') {
    return err.message;
  }
  return fallback;
}

function getHarnessAnswer(result: {
  answer?: string | null;
  clarification?: string | null;
  status?: string;
  failure?: { message?: string } | null;
}): string {
  if (result.answer) return result.answer;
  if (result.clarification) return `${result.clarification}\n\n你可以直接在下方继续补充，我会结合当前对话接着分析。`;
  if (result.failure?.message) return `这次分析没有完成：${result.failure.message}\n\n请直接补充或修正问题，我会沿用当前对话上下文继续处理。`;
  return result.status === 'completed' ? '分析已完成。' : '本轮分析暂未完成，请继续告诉我你的要求。';
}

type AppTab = 'ask' | 'workspace' | 'packs' | 'sources' | 'mounting' | 'settings' | 'profile';

const MANAGEMENT_TABS: AppTab[] = ['packs', 'sources', 'settings', 'mounting', 'profile'];

const UserAvatar = ({ name, size = 'sm' }: { name: string; size?: 'sm' | 'lg' }) => {
  const label = (name || '用户').trim().slice(0, 1).toUpperCase();
  return (
    <span className={`inline-flex shrink-0 items-center justify-center rounded-full bg-indigo-100 font-bold text-indigo-700 ring-1 ring-indigo-200 dark:bg-indigo-950/60 dark:text-indigo-300 dark:ring-indigo-800 ${size === 'lg' ? 'h-12 w-12 text-base' : 'h-8 w-8 text-xs'}`}>
      {label}
    </span>
  );
};

const PageLoadingState = ({ label }: { label: string }) => (
  <ManagementPage>
    <div className="management-card flex min-h-64 items-center justify-center">
      <div className="flex items-center gap-2 text-xs text-slate-400">
        <RefreshCw className="h-4 w-4 animate-spin text-indigo-500" />
        <span>{label}</span>
      </div>
    </div>
  </ManagementPage>
);

export default function App() {
  const [systemNotice, setSystemNotice] = useState<string | null>(null);
  const [systemConfirm, setSystemConfirm] = useState<{
    message: string;
    resolve: (confirmed: boolean) => void;
  } | null>(null);
  // Navigation & Theme
  const [activeTab, setActiveTab] = useState<AppTab>(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.hash.replace(/^#/, ''));
      const hashTab = params.get('tab') as AppTab;
      if (hashTab === 'profile') return 'sources';
      if (hashTab === 'mounting') return 'packs';
      if (['ask', 'workspace', 'packs', 'sources', 'settings'].includes(hashTab)) {
        return hashTab;
      }
      return (window.localStorage.getItem('sqbi.activeTab') as AppTab) || 'ask';
    }
    return 'ask';
  });

  const [selectedProfileDsId, setSelectedProfileDsId] = useState<string>(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.hash.replace(/^#/, ''));
      return params.get('dsId') || 'oracle_tms';
    }
    return 'oracle_tms';
  });

  const [selectedSpaceId, setSelectedSpaceId] = useState<string | null>(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.hash.replace(/^#/, ''));
      return params.get('spaceId');
    }
    return null;
  });

  const [packsTab, setPacksTab] = useState<'list' | 'mounting'>(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.hash.replace(/^#/, ''));
      const hashTab = params.get('tab') as AppTab;
      if (hashTab === 'mounting') return 'mounting';
      return (params.get('subTab') as 'list' | 'mounting') || 'list';
    }
    return 'list';
  });
  const [preSelectedFieldId, setPreSelectedFieldId] = useState<string | null>(null);
  const [focusSemanticSpace, setFocusSemanticSpace] = useState<{ dsId: string; spaceId: string; nonce: number } | null>(null);
  const selectedProfileDsIdRef = useRef(selectedProfileDsId);
  const selectedSpaceIdRef = useRef(selectedSpaceId);
  const [darkMode] = useState<boolean>(() => {
    if (typeof window !== 'undefined') {
      return window.localStorage.getItem('sqbi.darkMode') === 'true';
    }
    return false;
  });

  useEffect(() => {
    const originalAlert = window.alert;
    window.alert = (message?: unknown) => setSystemNotice(String(message ?? ''));
    return () => {
      window.alert = originalAlert;
    };
  }, []);

  useEffect(() => {
    if (!systemNotice) return;
    const timer = window.setTimeout(() => setSystemNotice(null), 4500);
    return () => window.clearTimeout(timer);
  }, [systemNotice]);

  useEffect(() => registerSystemConfirm((message, resolve) => {
    setSystemConfirm({ message, resolve });
  }), []);

  // Global Backend states
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [backendError, setBackendError] = useState<string | null>(null);
  const [dataSources, setDataSources] = useState<DataSource[]>([]);
  const [fields, setFields] = useState<SemanticField[]>([]);
  const [metrics, setMetrics] = useState<MetricDefinition[]>([]);
  const [skills, setSkills] = useState<SkillDefinition[]>([]);
  const [reports, setReports] = useState<ReportDefinition[]>([]);
  const [callableAssets, setCallableAssets] = useState<CallableAsset[]>([]);
  const [initialDataLoaded, setInitialDataLoaded] = useState(false);

  // User Authentication / RLS contexts — populated for real via
  // api.ensureLocalSession() once the backend responds (see checkHealth).
  const [userContext, setUserContext] = useState<UserContext>({
    user_id: '',
    display_name: '',
    org_id: '',
    org_name: '',
    role_ids: []
  });
  const [loginUsername, setLoginUsername] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [loginError, setLoginError] = useState<string | null>(null);
  const [isLoggingIn, setIsLoggingIn] = useState(false);
  const [managedUsers, setManagedUsers] = useState<ManagedUser[]>([]);
  const [newUser, setNewUser] = useState({ username: '', display_name: '', password: '', role: 'user' as 'admin' | 'user' });
  const [newUserModalOpen, setNewUserModalOpen] = useState(false);
  const [isSavingUser, setIsSavingUser] = useState(false);
  const [editingUsername, setEditingUsername] = useState<string | null>(null);
  const [profileMenuOpen, setProfileMenuOpen] = useState(false);

  // Chat workspace states
  const [messages, setMessages] = useState<any[]>([
    { id: 'welcome', sender: 'assistant', text: '你好！我是 SQ-BI 助手。请问您需要查询什么物流数据或分析指标？', loading: false }
  ]);
  const [isHarnessMode, setIsHarnessMode] = useState<boolean>(true);
  const [chatSessionId, setChatSessionId] = useState<string | null>(null);
  const [chatSessions, setChatSessions] = useState<ChatSessionRecord[]>([]);
  const [inputText, setInputText] = useState('');
  const [loading, setLoading] = useState(false);
  const [showMetricDropdown, setShowMetricDropdown] = useState(false);
  const [filteredMetrics, setFilteredMetrics] = useState<CallableAsset[]>([]);
  const [showSkillDropdown, setShowSkillDropdown] = useState(false);
  const [filteredSkills, setFilteredSkills] = useState<CallableAsset[]>([]);
  const [showReportDropdown, setShowReportDropdown] = useState(false);
  const [filteredReports, setFilteredReports] = useState<CallableAsset[]>([]);

  // LLM and DB Configurations
  const [llmSettings, setLlmSettings] = useState<LlmSettings | null>(null);
  const [llmBaseUrl, setLlmBaseUrl] = useState('');
  const [llmModel, setLlmModel] = useState('');
  const [llmApiKey, setLlmApiKey] = useState('');
  const [llmTimeout, setLlmTimeout] = useState('60');
  const [isSavingLlm, setIsSavingLlm] = useState(false);
  const [isProbingLlm, setIsProbingLlm] = useState(false);
  const [llmProbe, setLlmProbe] = useState<{ healthy: boolean; latency_ms: number; message: string } | null>(null);



  // Lineage Drawer State
  const [activeLineage, setActiveLineage] = useState<Lineage | null>(null);
  const [showLineageDrawer, setShowLineageDrawer] = useState(false);
  const [showMetricDrawer, setShowMetricDrawer] = useState(false);
  const [selectedMetric, setSelectedMetric] = useState<MetricDefinition | null>(null);
  const [metricDependencies, setMetricDependencies] = useState<MetricDependencyRecord[]>([]);
  const [activeDataSourceId, setActiveDataSourceId] = useState<string>('');

  useEffect(() => {
    if (dataSources.length > 0 && !activeDataSourceId) {
      const defaultDs = dataSources.find(ds => ds.data_source_id === 'oracle_tms') || dataSources[0];
      setActiveDataSourceId(defaultDs.data_source_id);
    }
  }, [dataSources, activeDataSourceId]);

  const [editingPack, setEditingPack] = useState<EnterprisePack | null>(null);
  const [activeDeploymentId, setActiveDeploymentId] = useState<string | null>(null);

  const userRoleIds = userContext.role_ids || [];
  const isSystemAdmin = userRoleIds.includes('role-system-admin') || userRoleIds.includes('admin');

  useEffect(() => {
    selectedProfileDsIdRef.current = selectedProfileDsId;
    selectedSpaceIdRef.current = selectedSpaceId;
  }, [selectedProfileDsId, selectedSpaceId]);

  // Routing gate: keep unauthorized users away
  useEffect(() => {
    if (userContext.user_id && !isSystemAdmin && MANAGEMENT_TABS.includes(activeTab)) {
      setActiveTab('ask');
    }
  }, [activeTab, isSystemAdmin, userContext.user_id]);

  useEffect(() => {
    if (activeTab !== 'ask' || !userContext.user_id) return;
    void api.getCallableAssets(userContext.user_id)
      .then(setCallableAssets)
      .catch(error => console.error('刷新可调用资产失败:', error));
  }, [activeTab, userContext.user_id]);

  useEffect(() => {
    if (activeTab !== 'ask' || backendOnline !== true || !userContext.user_id) return;
    let cancelled = false;
    void api.getChatSessions(userContext.user_id)
      .then(async sessions => {
        if (cancelled) return;
        setChatSessions(sessions);
        if (sessions.length === 0 || sessions.some(session => session.session_id === chatSessionId)) return;
        const session = sessions[0];
        const history = await api.getChatMessages(userContext.user_id, session.session_id);
        if (cancelled) return;
        setChatSessionId(session.session_id);
        setMessages(history.map(item => ({
          id: item.message_id,
          sender: item.sender,
          text: item.text,
          ...(item.payload || {}),
          loading: false,
        })));
      })
      .catch(error => console.error('刷新对话历史失败:', error));
    return () => { cancelled = true; };
  }, [activeTab, backendOnline, chatSessionId, userContext.user_id]);

  // Sync routing state to Hash query parameters
  useEffect(() => {
    window.localStorage.setItem('sqbi.activeTab', activeTab);
    const params = new URLSearchParams();
    params.set('tab', activeTab);
    if (activeTab === 'sources') {
      if (selectedProfileDsId) {
        params.set('dsId', selectedProfileDsId);
      }
      if (selectedSpaceId) {
        params.set('spaceId', selectedSpaceId);
      }
    } else if (activeTab === 'packs') {
      params.set('subTab', packsTab);
    }
    const nextHash = params.toString();
    if (window.location.hash.slice(1) !== nextHash) {
      window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}#${nextHash}`);
    }
  }, [activeTab, selectedProfileDsId, selectedSpaceId, packsTab]);

  // Listen to browser navigation for deep links, pushState entries, and legacy redirects.
  useEffect(() => {
    const handleRouteChange = () => {
      const params = new URLSearchParams(window.location.hash.replace(/^#/, ''));
      let tab = params.get('tab') as AppTab;
      const dsId = params.get('dsId');
      const spaceId = params.get('spaceId');
      const subTab = params.get('subTab') as 'list' | 'mounting';
      const previousSpaceId = selectedSpaceIdRef.current;
      const previousDsId = selectedProfileDsIdRef.current;

      if (tab === 'profile') {
        tab = 'sources';
        if (dsId) {
          setSelectedProfileDsId(dsId);
        }
      }
      if (tab === 'mounting') {
        tab = 'packs';
        setPacksTab('mounting');
      }

      if (['ask', 'workspace', 'packs', 'sources', 'settings'].includes(tab)) {
        setActiveTab(userContext.user_id && !isSystemAdmin && MANAGEMENT_TABS.includes(tab) ? 'ask' : tab);
      }
      if (dsId) {
        setSelectedProfileDsId(dsId);
      }
      setSelectedSpaceId(spaceId);
      if (!spaceId && previousSpaceId && (tab === 'sources' || !tab)) {
        setFocusSemanticSpace({
          dsId: dsId || previousDsId,
          spaceId: previousSpaceId,
          nonce: Date.now()
        });
      }
      if (subTab) {
        setPacksTab(subTab);
      }
    };

    window.addEventListener('hashchange', handleRouteChange);
    window.addEventListener('popstate', handleRouteChange);
    // Initial check for legacy redirects
    handleRouteChange();
    return () => {
      window.removeEventListener('hashchange', handleRouteChange);
      window.removeEventListener('popstate', handleRouteChange);
    };
  }, [isSystemAdmin, userContext.user_id]);

  // Sync Dark Mode state
  useEffect(() => {
    const root = window.document.documentElement;
    window.localStorage.setItem('sqbi.darkMode', String(darkMode));
    if (darkMode) {
      root.classList.add('dark');
    } else {
      root.classList.remove('dark');
    }
  }, [darkMode]);

  // Init and fetch resources
  const checkHealth = async () => {
    setInitialDataLoaded(false);
    setBackendOnline(null);
    setBackendError(null);
    try {
      await api.getHealth();
      setBackendOnline(true);

      // Auth first: subsequent admin-gated calls need X-Session-Id attached.
      const currentUser = await api.ensureLocalSession().catch(() => null);
      if (currentUser?.user_id) {
        setUserContext(currentUser);
        try {
          const sessions = await api.getChatSessions(currentUser.user_id);
          const session = sessions[0] || await api.createChatSession({
            user_id: currentUser.user_id,
            title: '智慧问数会话',
          });
          setChatSessions(sessions.length === 0 ? [session] : sessions);
          setChatSessionId(session.session_id);
          const history = await api.getChatMessages(currentUser.user_id, session.session_id);
          if (history.length > 0) {
            setMessages(history.map(item => ({
              id: item.message_id,
              sender: item.sender,
              text: item.text,
              ...(item.payload || {}),
              loading: false,
            })));
          }
        } catch (error) {
          console.error('首次加载对话历史失败，将在进入问数页后重试:', error);
        }
        setCallableAssets(await api.getCallableAssets(currentUser.user_id).catch(() => []));
      }

      const [sourcesList, fieldsList, metricsList, skillsList, reportsList, settings] = await Promise.all([
        api.getDataSources().catch(() => []),
        api.getFields().catch(() => []),
        api.getMetrics().catch(() => []),
        api.getSkills().catch(() => []),
        api.getReports().catch(() => []),
        api.getLlmSettings().catch(() => null),
        api.getDbSettings().catch(() => null)
      ]);

      setDataSources(sourcesList);
      setFields(fieldsList);
      setMetrics(metricsList);
      setSkills(skillsList);
      setReports(reportsList as any[]);

      if (settings) {
        setLlmSettings(settings);
        setLlmBaseUrl(settings.base_url);
        setLlmModel(settings.model);
        setLlmTimeout(String(settings.timeout_seconds));
      }

      setInitialDataLoaded(true);

    } catch (err: unknown) {
      setBackendOnline(false);
      setBackendError(getErrorMessage(err, '无法连接到本地后端服务。'));
      setInitialDataLoaded(true);
    }
  };

  useEffect(() => {
    void checkHealth();
  }, []);

  const refreshAllData = async () => {
    try {
      const [metricsList, skillsList, reportsList] = await Promise.all([
        api.getMetrics().catch(() => []),
        api.getSkills().catch(() => []),
        api.getReports().catch(() => [])
      ]);
      setMetrics(metricsList);
      setSkills(skillsList);
      setReports(reportsList as any[]);
      if (userContext.user_id) {
        setCallableAssets(await api.getCallableAssets(userContext.user_id).catch(() => []));
      }
    } catch (e) {
      console.error(e);
    }
  };

  const refreshSources = async () => {
    try {
      const list = await api.getDataSources();
      setDataSources(list);
    } catch (e) {
      console.error(e);
    }
  };

  const loadChatSession = async (session: ChatSessionRecord) => {
    setChatSessionId(session.session_id);
    setActiveTab('ask');
    const history = await api.getChatMessages(userContext.user_id, session.session_id).catch(() => []);
    setMessages(history.length > 0 ? history.map(item => ({
      id: item.message_id,
      sender: item.sender,
      text: item.text,
      ...(item.payload || {}),
      loading: false,
    })) : [{
      id: `welcome_${session.session_id}`,
      sender: 'assistant',
      text: '这是一个新对话。告诉我你想查询的数据或继续分析的问题。',
      loading: false,
    }]);
  };

  const createNewChat = async () => {
    if (!userContext.user_id) return;
    const session = await api.createChatSession({
      user_id: userContext.user_id,
      title: '新对话',
    });
    setChatSessions(current => [session, ...current]);
    setChatSessionId(session.session_id);
    setMessages([{
      id: `welcome_${session.session_id}`,
      sender: 'assistant',
      text: '新对话已创建。你可以直接提问，或使用 @ 指标、/ 技能、# 报表。',
      loading: false,
    }]);
    setInputText('');
    setActiveTab('ask');
  };

  const deleteChatSession = async (session: ChatSessionRecord) => {
    const confirmed = await confirmAction(`确认删除对话“${session.title || '未命名对话'}”吗？删除后将不再显示在历史记录中。`);
    if (!confirmed) return;
    await api.archiveChatSession(session.session_id, { user_id: userContext.user_id });
    const remaining = chatSessions.filter(item => item.session_id !== session.session_id);
    setChatSessions(remaining);
    if (chatSessionId !== session.session_id) return;
    if (remaining.length > 0) {
      await loadChatSession(remaining[0]);
    } else {
      await createNewChat();
    }
  };

  // Submit chat query handler
  const handleSubmitQuery = async (overrideText?: string) => {
    const textToSubmit = overrideText !== undefined ? overrideText : inputText;
    if (!textToSubmit.trim() || loading) return;

    const queryText = textToSubmit;
    if (overrideText === undefined) {
      setInputText('');
    }
    setLoading(true);

    const userMessageId = `msg_${Math.random().toString(36).substr(2, 6)}`;
    const botMessageId = `msg_${Math.random().toString(36).substr(2, 6)}`;

    setMessages(prev => [
      ...prev,
      { id: userMessageId, sender: 'user', text: queryText }
    ]);

    let sessionId = chatSessionId;
    if (!sessionId && userContext.user_id) {
      const session = await api.createChatSession({
        user_id: userContext.user_id,
        title: queryText.slice(0, 32),
      }).catch(() => null);
      sessionId = session?.session_id || null;
      if (sessionId && session) {
        setChatSessionId(sessionId);
        setChatSessions(current => [session, ...current.filter(item => item.session_id !== session.session_id)]);
      }
    }
    if (sessionId) {
      void api.createChatMessage({
        user_id: userContext.user_id,
        session_id: sessionId,
        sender: 'user',
        text: queryText,
      }).catch(() => null);
    }

    setMessages(prev => [
      ...prev,
      {
        id: botMessageId,
        sender: 'assistant',
        text: isHarnessMode ? '正在调用智能规划器编排工具时序...' : '正在解析和执行问数意图，请稍后...',
        loading: true
      }
    ]);

    try {
      const result = await api.queryHarness({
          question: queryText,
          context: {
            user_id: userContext.user_id,
            data_source_id: activeDataSourceId,
            environment: 'default',
            workspace_id: userContext.user_id
          },
          execute: true,
          session_id: sessionId,
          conversation: messages
            .filter(message => !message.loading && (message.sender === 'user' || message.sender === 'assistant'))
            .slice(-12)
            .map(message => ({ role: message.sender, text: String(message.text || '') })),
          data_source_ids: dataSources.map(source => source.data_source_id),
      });

      const assistantText = getHarnessAnswer(result);

      setMessages(prev =>
        prev.map(msg =>
          msg.id === botMessageId
            ? {
                id: botMessageId,
                sender: 'assistant',
                text: assistantText,
                harnessResult: result,
                loading: false
              }
            : msg
        )
      );
      if (sessionId) {
        void api.createChatMessage({
          user_id: userContext.user_id,
          session_id: sessionId,
          sender: 'assistant',
          text: assistantText,
          payload: { harnessResult: result },
        }).catch(() => null);
      }
    } catch (err: unknown) {
      const errorMessage = getErrorMessage(err, '未知错误，无法执行查询。');
      setMessages(prev =>
        prev.map(msg =>
          msg.id === botMessageId
            ? {
                id: botMessageId,
                sender: 'assistant',
                text: `意图规划终止，原因：${errorMessage}`,
                error: errorMessage,
                loading: false
              }
            : msg
        )
      );
    } finally {
      setLoading(false);
    }
  };

  const handleHarnessClarifySubmit = async (runId: string, clarifyText: string) => {
    setLoading(true);
    const userMessageId = `msg_${Math.random().toString(36).substr(2, 6)}`;
    const botMessageId = `msg_${Math.random().toString(36).substr(2, 6)}`;

    setMessages(prev => [
      ...prev,
      { id: userMessageId, sender: 'user', text: `澄清说明: ${clarifyText}` }
    ]);

    setMessages(prev => [
      ...prev,
      { id: botMessageId, sender: 'assistant', text: '正在基于您的澄清信息继续执行智能规划...', loading: true }
    ]);

    try {
      const result = await api.queryHarness({
        question: clarifyText,
        context: {
          user_id: userContext.user_id,
          data_source_id: activeDataSourceId,
          environment: 'default',
          workspace_id: userContext.user_id
        },
        execute: true,
        session_id: chatSessionId,
        conversation: messages
          .filter(message => !message.loading && (message.sender === 'user' || message.sender === 'assistant'))
          .slice(-12)
          .map(message => ({ role: message.sender, text: String(message.text || '') })),
        data_source_ids: dataSources.map(source => source.data_source_id),
        continuation: {
          run_id: runId,
          clarification: clarifyText
        }
      });

      const assistantText = getHarnessAnswer(result);

      setMessages(prev =>
        prev.map(msg =>
          msg.id === botMessageId
            ? {
                id: botMessageId,
                sender: 'assistant',
                text: assistantText,
                harnessResult: result,
                loading: false
              }
            : msg
        )
      );
      if (chatSessionId) {
        void Promise.all([
          api.createChatMessage({
            user_id: userContext.user_id,
            session_id: chatSessionId,
            sender: 'user',
            text: clarifyText,
          }),
          api.createChatMessage({
            user_id: userContext.user_id,
            session_id: chatSessionId,
            sender: 'assistant',
            text: assistantText,
            payload: { harnessResult: result },
          }),
        ]).catch(() => null);
      }
    } catch (err: unknown) {
      const errorMessage = getErrorMessage(err, '智能规划续行失败。');
      setMessages(prev =>
        prev.map(msg =>
          msg.id === botMessageId
            ? {
                id: botMessageId,
                sender: 'assistant',
                text: `规划执行失败，原因：${errorMessage}`,
                error: errorMessage,
                loading: false
              }
            : msg
        )
      );
    } finally {
      setLoading(false);
    }
  };

  const handleHarnessConfirmSubmit = async (runId: string, token: string) => {
    setLoading(true);
    const userMessageId = `msg_${Math.random().toString(36).substr(2, 6)}`;
    const botMessageId = `msg_${Math.random().toString(36).substr(2, 6)}`;

    setMessages(prev => [
      ...prev,
      { id: userMessageId, sender: 'user', text: '确认执行持久化保存资产。' }
    ]);

    setMessages(prev => [
      ...prev,
      { id: botMessageId, sender: 'assistant', text: '已收到安全授权确认，正在提交写入...', loading: true }
    ]);

    try {
      const result = await api.queryHarness({
        question: '[Continuation Confirm]',
        context: {
          user_id: userContext.user_id,
          data_source_id: activeDataSourceId,
          environment: 'default',
          workspace_id: userContext.user_id
        },
        execute: true,
        session_id: chatSessionId,
        conversation: messages
          .filter(message => !message.loading && (message.sender === 'user' || message.sender === 'assistant'))
          .slice(-12)
          .map(message => ({ role: message.sender, text: String(message.text || '') })),
        data_source_ids: dataSources.map(source => source.data_source_id),
        continuation: {
          run_id: runId,
          confirmation_token: token
        }
      });

      const assistantText = getHarnessAnswer(result);

      setMessages(prev =>
        prev.map(msg =>
          msg.id === botMessageId
            ? {
                id: botMessageId,
                sender: 'assistant',
                text: assistantText,
                harnessResult: result,
                loading: false
              }
            : msg
        )
      );

      if (result.status === 'completed') {
        await refreshAllData();
      }
    } catch (err: unknown) {
      const errorMessage = getErrorMessage(err, '确认执行持久化资产写入失败。');
      setMessages(prev =>
        prev.map(msg =>
          msg.id === botMessageId
            ? {
                id: botMessageId,
                sender: 'assistant',
                text: `写入失败，原因：${errorMessage}`,
                error: errorMessage,
                loading: false
              }
            : msg
        )
      );
    } finally {
      setLoading(false);
    }
  };

  const handleHarnessCancel = () => {
    setMessages(prev => [
      ...prev,
      {
        id: `cancel_${Math.random().toString(36).substr(2, 6)}`,
        sender: 'assistant',
        text: '已取消本次持久化保存资产申请，未进行任何持久化写入。'
      }
    ]);
  };

  const handleClarificationSubmit = (interpretation: string) => {
    handleSubmitQuery(interpretation);
  };

  const handleCorrectionSubmit = (correctionText: string) => {
    const lastUserMsg = [...messages].reverse().find(msg => msg.sender === 'user');
    const baseText = lastUserMsg ? lastUserMsg.text : '';
    const cleanBaseText = baseText.replace(/\s*\(修正:.*?\)/g, '').trim();
    const combinedText = cleanBaseText ? `${cleanBaseText} (修正: ${correctionText})` : correctionText;
    handleSubmitQuery(combinedText);
  };

  const handleSaveExplorationAsMetric = async (payload: SaveExplorationAsMetricRequest) => {
    await api.saveExplorationAsMetric(payload);
    await refreshAllData();
  };

  // Autocomplete helpers
  const handleInputChange = (text: string) => {
    setInputText(text);

    const filterCallableAssets = (assetType: CallableAsset['asset_type'], search: string) =>
      callableAssets.filter(item => {
        if (item.asset_type !== assetType) return false;
        return [item.name, item.code, item.asset_ref.asset.local_code]
          .some(value => String(value || '').toLowerCase().includes(search));
      });

    const atMatch = text.match(/@([^\s@]*)$/);
    if (atMatch) {
      const search = atMatch[1].toLowerCase();
      setFilteredMetrics(filterCallableAssets('metric', search));
      setShowMetricDropdown(true);
      setShowSkillDropdown(false);
      setShowReportDropdown(false);
      return;
    }

    const slashMatch = text.match(/\/([^\s/]*)$/);
    if (slashMatch) {
      const search = slashMatch[1].toLowerCase();
      setFilteredSkills(filterCallableAssets('skill', search));
      setShowSkillDropdown(true);
      setShowMetricDropdown(false);
      setShowReportDropdown(false);
      return;
    }

    const hashMatch = text.match(/#([^\s#]*)$/);
    if (hashMatch) {
      const search = hashMatch[1].toLowerCase();
      setFilteredReports(filterCallableAssets('report', search));
      setShowReportDropdown(true);
      setShowMetricDropdown(false);
      setShowSkillDropdown(false);
      return;
    }

    setShowMetricDropdown(false);
    setShowSkillDropdown(false);
    setShowReportDropdown(false);
  };

  const selectMetric = (metric: CallableAsset) => {
    const updated = inputText.replace(/@([^\s@]*)$/, `@${metric.name} `);
    setInputText(updated);
    setShowMetricDropdown(false);
  };

  const selectSkill = (skill: CallableAsset) => {
    const updated = inputText.replace(/\/([^\s/]*)$/, `/${skill.name} `);
    setInputText(updated);
    setShowSkillDropdown(false);
  };

  const selectReport = (report: CallableAsset) => {
    const updated = inputText.replace(/#([^\s#]*)$/, `#${report.name} `);
    setInputText(updated);
    setShowReportDropdown(false);
  };

  useEffect(() => {
    if (!/[@/#][^\s@/#]*$/.test(inputText)) return;
    handleInputChange(inputText);
    // Recompute an already-open trigger after async catalogs become available.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [callableAssets]);

  // Settings Save Handlers
  const handleSaveLlmSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSavingLlm(true);
    try {
      const updated = await api.updateLlmSettings({
        base_url: llmBaseUrl,
        model: llmModel,
        timeout_seconds: Number(llmTimeout) || 60,
        ...(llmApiKey.trim() ? { api_key: llmApiKey.trim() } : {}),
      });
      setLlmSettings(updated);
      setLlmApiKey('');
      alert('LLM 连接配置保存成功。');
    } catch (err: unknown) {
      alert(`保存 LLM 配置失败: ${getErrorMessage(err, '未知错误')}`);
    } finally {
      setIsSavingLlm(false);
    }
  };

  const handleProbeLlm = async () => {
    setIsProbingLlm(true);
    setLlmProbe(null);
    try {
      setLlmProbe(await api.probeLlmSettings());
    } catch (error) {
      setLlmProbe({ healthy: false, latency_ms: 0, message: getErrorMessage(error, '连接测试失败。') });
    } finally {
      setIsProbingLlm(false);
    }
  };

  const handleLogin = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsLoggingIn(true);
    setLoginError(null);
    try {
      const result = await api.login(loginUsername.trim(), loginPassword);
      setUserContext({
        user_id: result.user_id,
        display_name: result.display_name,
        org_id: result.org_id,
        role_ids: result.role_ids,
      });
      setLoginPassword('');
      await refreshAllData();
    } catch (error) {
      setLoginError(getErrorMessage(error, '用户名或密码不正确。'));
    } finally {
      setIsLoggingIn(false);
    }
  };

  const loadManagedUsers = useCallback(async () => {
    try {
      setManagedUsers(await api.listManagedUsers());
    } catch (error) {
      window.alert(`加载用户失败：${getErrorMessage(error, '未知错误')}`);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'settings' && isSystemAdmin) {
      void loadManagedUsers();
    }
  }, [activeTab, isSystemAdmin, loadManagedUsers]);

  const handleCreateManagedUser = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSavingUser(true);
    try {
      if (editingUsername) {
        const updated = await api.updateManagedUser(editingUsername, {
          new_username: newUser.username.trim(),
          display_name: newUser.display_name,
          role: newUser.role,
          ...(newUser.password ? { password: newUser.password } : {}),
        });
        if (userContext.user_id === editingUsername) {
          setUserContext(current => ({
            ...current,
            user_id: updated.user_id,
            display_name: updated.display_name,
            role_ids: [updated.role],
          }));
        }
      } else {
        await api.createManagedUser(newUser);
      }
      setNewUser({ username: '', display_name: '', password: '', role: 'user' });
      setEditingUsername(null);
      setNewUserModalOpen(false);
      await loadManagedUsers();
      alert(editingUsername ? '用户信息已更新。' : '用户已创建。');
    } catch (error) {
      alert(`${editingUsername ? '更新' : '创建'}用户失败：${getErrorMessage(error, '未知错误')}`);
    } finally {
      setIsSavingUser(false);
    }
  };

  const openCreateUser = () => {
    setEditingUsername(null);
    setNewUser({ username: '', display_name: '', password: '', role: 'user' });
    setNewUserModalOpen(true);
  };

  const openEditUser = (item: ManagedUser) => {
    setEditingUsername(item.user_id);
    setNewUser({
      username: item.user_id,
      display_name: item.display_name,
      password: '',
      role: item.role,
    });
    setNewUserModalOpen(true);
  };

  const handleUserRoleChange = async (username: string, role: 'admin' | 'user') => {
    try {
      const updated = await api.updateManagedUser(username, { role });
      if (userContext.user_id === username) {
        setUserContext(current => ({ ...current, role_ids: [updated.role] }));
      }
      await loadManagedUsers();
      alert('用户角色已更新。');
    } catch (error) {
      alert(`更新角色失败：${getErrorMessage(error, '未知错误')}`);
    }
  };

  const handleDeleteManagedUser = async (username: string) => {
    if (!await confirmAction(`确认删除账户“${username}”吗？此操作不能恢复。`)) return;
    try {
      await api.deleteManagedUser(username);
      await loadManagedUsers();
      alert('用户已删除。');
    } catch (error) {
      alert(`删除用户失败：${getErrorMessage(error, '未知错误')}`);
    }
  };



  const openMetricDrawer = async (metric: MetricDefinition) => {
    setSelectedMetric(metric);
    setShowMetricDrawer(true);
    try {
      setMetricDependencies(await api.getMetricDependencies(metric.metric_code));
    } catch {
      setMetricDependencies([]);
    }
  };

  const openMetricDrawerById = async (metricId: string) => {
    const normalized = metricId.trim().toLowerCase();
    const metric = metrics.find(item => (
      item.metric_code.toLowerCase() === normalized ||
      item.name.toLowerCase() === normalized ||
      item.name.toLowerCase().includes(normalized)
    ));
    if (metric) {
      await openMetricDrawer(metric);
    }
  };

  const alert = (message: string) => {
    window.alert(message);
  };

  return (
    <div className="h-screen overflow-hidden bg-slate-50 text-slate-800 dark:bg-slate-950 dark:text-slate-100 flex flex-col font-sans transition-colors duration-150">

      {systemNotice && (
        <div role="status" aria-live="polite" className="fixed top-5 right-5 z-[100] max-w-sm rounded-xl border border-indigo-200 dark:border-indigo-800 bg-indigo-50/95 dark:bg-indigo-950/95 px-4 py-3 shadow-xl backdrop-blur-sm flex items-start gap-2.5 text-xs text-indigo-800 dark:text-indigo-300">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span className="leading-relaxed font-medium">{systemNotice}</span>
          <button type="button" onClick={() => setSystemNotice(null)} className="ml-1 opacity-60 hover:opacity-100" aria-label="关闭提示">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {systemConfirm && (
        <ModalFrame>
          <div role="alertdialog" aria-modal="true" aria-labelledby="system-confirm-title">
            <div className="flex items-start gap-3">
              <div className="w-9 h-9 shrink-0 rounded-xl bg-amber-50 dark:bg-amber-950/30 text-amber-600 dark:text-amber-400 flex items-center justify-center">
                <AlertTriangle className="w-4.5 h-4.5" />
              </div>
              <div>
                <h2 id="system-confirm-title" className="text-sm font-bold text-slate-900 dark:text-white">请确认操作</h2>
                <p className="mt-1.5 text-xs leading-relaxed text-slate-600 dark:text-slate-300">{systemConfirm.message}</p>
              </div>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <ActionButton type="button" onClick={() => {
                systemConfirm.resolve(false);
                setSystemConfirm(null);
              }}>取消</ActionButton>
              <ActionButton variant="primary" type="button" autoFocus onClick={() => {
                systemConfirm.resolve(true);
                setSystemConfirm(null);
              }}>确认</ActionButton>
            </div>
          </div>
        </ModalFrame>
      )}

      {!userContext.user_id && (
        <div className="fixed inset-0 z-[120] flex items-center justify-center bg-slate-100/90 p-4 backdrop-blur-sm dark:bg-slate-950/90">
          <form onSubmit={handleLogin} className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl dark:border-slate-800 dark:bg-slate-900">
            <div className="mb-6 flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600 text-sm font-bold text-white shadow-sm">SQ</div>
              <div><h1 className="text-base font-bold text-slate-900 dark:text-white">登录 SQ-BI</h1><p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">使用您的平台账户继续。</p></div>
            </div>
            <div className="space-y-4">
              <div><label className="mb-1 block text-xs font-semibold text-slate-600 dark:text-slate-300">用户名</label><input autoFocus required autoComplete="username" value={loginUsername} onChange={event => setLoginUsername(event.target.value)} className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm outline-none focus:border-indigo-500 dark:border-slate-700 dark:bg-slate-950" /></div>
              <div><label className="mb-1 block text-xs font-semibold text-slate-600 dark:text-slate-300">密码</label><input required type="password" autoComplete="current-password" value={loginPassword} onChange={event => setLoginPassword(event.target.value)} className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm outline-none focus:border-indigo-500 dark:border-slate-700 dark:bg-slate-950" /></div>
              {loginError && <p role="alert" className="rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:bg-rose-950/40 dark:text-rose-300">{loginError}</p>}
              <button type="submit" disabled={isLoggingIn || backendOnline === false} className="management-primary-action w-full justify-center py-2.5 text-sm">{isLoggingIn ? '登录中…' : '登录'}</button>
            </div>
          </form>
        </div>
      )}

      {/* 1. Integration Status Banner */}
      {backendOnline === false && (
        <div className="bg-rose-500/10 dark:bg-rose-950/20 border-b border-rose-500/20 text-rose-700 dark:text-rose-400 px-4 py-3 flex items-center justify-between text-xs transition-all">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-rose-500 animate-pulse animate-duration-1000" />
            <span>
              <strong>集成状态告警</strong>：{backendError || '本地 SQ-BI 后端服务断开连接。系统目前处于离线状态，前端交互均将受阻。'}
            </span>
          </div>
          <button
            onClick={checkHealth}
            className="flex items-center gap-1 bg-rose-600 hover:bg-rose-700 text-white px-3 py-1 rounded text-xs transition font-semibold"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            重新连接
          </button>
        </div>
      )}

      {/* Main Workspace Frame */}
      <div className="flex min-h-0 flex-1 overflow-hidden">

        {/* 2. Left Sidebar Navigation */}
        <aside className="h-full w-64 shrink-0 bg-white dark:bg-slate-900 border-r border-slate-200 dark:border-slate-800 flex flex-col z-10 select-none overflow-hidden text-left">
          <div className="flex min-h-0 flex-1 flex-col">
            {/* System Logo */}
            <div className="p-5 border-b border-slate-100 dark:border-slate-800 flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center text-white font-bold text-lg shadow-sm">
                SQ
              </div>
              <div>
                <h1 className="text-sm font-bold text-slate-900 dark:text-white leading-none">SQ-BI 精准分析</h1>
                <span className="text-[9px] text-slate-450 tracking-wider">确定性语义架构</span>
              </div>
            </div>

            {/* Navigation Tabs */}
            <nav className="flex-1 p-3 space-y-4 overflow-y-auto">
              {/* Consumption Layer */}
              <div className="space-y-1">
                <span className="px-3 text-[9px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider block mb-1">数据消费层</span>

                <button
                  id="nav-ask"
                  onClick={() => setActiveTab('ask')}
                  className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-semibold transition-all ${
                    activeTab === 'ask'
                      ? 'bg-indigo-50 dark:bg-indigo-950/30 text-indigo-650 dark:text-indigo-400'
                      : 'text-slate-600 hover:bg-slate-50 dark:text-slate-400 dark:hover:bg-slate-800/40'
                  }`}
                >
                  <MessageSquare className="w-4 h-4" />
                  <span>智能问数</span>
                </button>

                <button
                  id="nav-workspace"
                  onClick={() => setActiveTab('workspace')}
                  className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-semibold transition-all ${
                    activeTab === 'workspace'
                      ? 'bg-indigo-50 dark:bg-indigo-950/30 text-indigo-650 dark:text-indigo-400'
                      : 'text-slate-600 hover:bg-slate-50 dark:text-slate-400 dark:hover:bg-slate-800/40'
                  }`}
                >
                  <TrendingUp className="w-4 h-4" />
                  <span>个人空间</span>
                </button>
              </div>

              {/* Administration Layer (Gate role check) */}
              {isSystemAdmin && (
                <div className="space-y-1 pt-2 border-t border-slate-100 dark:border-slate-800">
                  <span className="px-3 text-[9px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider block mb-1">系统管理层</span>

                  <button
                    id="nav-sources"
                    onClick={() => { setActiveTab('sources'); setSelectedSpaceId(null); }}
                    className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-semibold transition-all ${
                      activeTab === 'sources'
                        ? 'bg-indigo-50 dark:bg-indigo-950/30 text-indigo-650 dark:text-indigo-400'
                        : 'text-slate-600 hover:bg-slate-50 dark:text-slate-400 dark:hover:bg-slate-800/40'
                    }`}
                  >
                    <Database className="w-4 h-4" />
                    <span>数据库连接</span>
                  </button>

                  <button
                    id="nav-packs"
                    onClick={() => { setActiveTab('packs'); setPacksTab('list'); }}
                    className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-semibold transition-all ${
                      activeTab === 'packs'
                        ? 'bg-indigo-50 dark:bg-indigo-950/30 text-indigo-650 dark:text-indigo-400'
                        : 'text-slate-600 hover:bg-slate-50 dark:text-slate-400 dark:hover:bg-slate-800/40'
                    }`}
                  >
                    <Package className="w-4 h-4" />
                    <span>领域包管理</span>
                  </button>
                </div>
              )}

              <div className="space-y-1 border-t border-slate-100 pt-3 dark:border-slate-800">
                <div className="flex items-center justify-between px-3">
                  <span className="text-[9px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">对话历史</span>
                  <button
                    type="button"
                    onClick={() => void createNewChat()}
                    className="rounded-md p-1 text-slate-400 hover:bg-indigo-50 hover:text-indigo-600 dark:hover:bg-indigo-950/30 dark:hover:text-indigo-300"
                    title="新建对话"
                    aria-label="新建对话"
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </button>
                </div>
                <div className="max-h-48 space-y-0.5 overflow-y-auto pr-1 [scrollbar-width:thin]">
                  {chatSessions.map(session => (
                    <div key={session.session_id} className={`group flex items-center rounded-lg transition-colors ${chatSessionId === session.session_id && activeTab === 'ask' ? 'bg-indigo-50 dark:bg-indigo-950/30' : 'hover:bg-slate-50 dark:hover:bg-slate-800/50'}`}>
                      <button
                        type="button"
                        onClick={() => void loadChatSession(session)}
                        title={session.title}
                        className={`min-w-0 flex-1 truncate py-2 pl-3 pr-1 text-left text-[11px] ${chatSessionId === session.session_id && activeTab === 'ask' ? 'font-bold text-indigo-700 dark:text-indigo-300' : 'text-slate-500 group-hover:text-slate-800 dark:text-slate-400 dark:group-hover:text-slate-200'}`}
                      >
                        {session.title || '未命名对话'}
                      </button>
                      <button
                        type="button"
                        onClick={() => void deleteChatSession(session)}
                        title="删除对话"
                        aria-label={`删除对话 ${session.title || '未命名对话'}`}
                        className="mr-1 shrink-0 rounded p-1 text-slate-300 opacity-0 transition hover:bg-rose-50 hover:text-rose-600 group-hover:opacity-100 focus:opacity-100 dark:text-slate-600 dark:hover:bg-rose-950/30 dark:hover:text-rose-400"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                  ))}
                  {chatSessions.length === 0 && <p className="px-3 py-2 text-[10px] text-slate-400">暂无历史对话</p>}
                </div>
              </div>
            </nav>

            {/* Profile Bar */}
            <div className="relative shrink-0 border-t border-slate-100 bg-slate-50/50 p-4 dark:border-slate-800 dark:bg-slate-900/30">
              <button type="button" onClick={() => setProfileMenuOpen(value => !value)} className="flex min-w-0 items-center gap-2 pr-8 text-left" aria-expanded={profileMenuOpen}>
                <UserAvatar name={userContext.display_name || userContext.user_id} />
                <div className="max-w-[10rem] truncate text-xs font-bold leading-none text-slate-800 dark:text-slate-200">{userContext.display_name || userContext.user_id}</div>
              </button>

              {profileMenuOpen && (
                <>
                  <button type="button" aria-label="关闭账户信息" onClick={() => setProfileMenuOpen(false)} className="fixed inset-0 z-40 cursor-default" />
                  <div className="absolute bottom-[calc(100%+0.5rem)] left-3 z-50 w-64 rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-2xl dark:border-slate-700 dark:bg-slate-900">
                    <div className="flex items-center gap-3">
                      <UserAvatar name={userContext.display_name || userContext.user_id} size="lg" />
                      <div className="min-w-0"><p className="truncate text-sm font-bold text-slate-900 dark:text-white">{userContext.display_name || userContext.user_id}</p><p className="mt-1 truncate text-[11px] text-slate-500">@{userContext.user_id}</p></div>
                    </div>
                    <div className="mt-4 flex items-center justify-between rounded-xl bg-slate-50 px-3 py-2 dark:bg-slate-800/60"><span className="text-[11px] text-slate-500">账户角色</span><span className="rounded-full bg-indigo-100 px-2 py-0.5 text-[10px] font-bold text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300">{isSystemAdmin ? '管理员' : '一般用户'}</span></div>
                    {isSystemAdmin && <button type="button" onClick={() => { setProfileMenuOpen(false); setActiveTab('settings'); }} className="mt-3 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs font-bold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800">进入账户管理</button>}
                  </div>
                </>
              )}

              <div className="absolute right-3 top-1/2 -translate-y-1/2">
                {isSystemAdmin && <button
                  type="button"
                  onClick={() => setActiveTab('settings')}
                  title="系统设置"
                  aria-label="系统设置"
                  className={`p-1.5 rounded-md transition-colors ${activeTab === 'settings' ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-300' : 'bg-slate-100 text-slate-500 hover:text-slate-700 dark:bg-slate-800 dark:text-slate-400 dark:hover:text-slate-200'}`}
                >
                  <Settings className="h-4 w-4" />
                </button>}
              </div>
            </div>
          </div>
        </aside>

        {/* 3. Main Dense Right Work Surface */}
        <main className="flex-1 flex flex-col min-w-0 overflow-hidden bg-slate-50 dark:bg-slate-950">
          <Suspense fallback={<PageLoadingState label="正在加载工作区…" />}>

          {/* Ask Data Panel */}
          {activeTab === 'ask' && (
            <AskDashboard
              messages={messages}
              userRoleIds={userRoleIds}
              fields={fields}
              darkMode={darkMode}
              queryText={inputText}
              setQueryText={handleInputChange}
              handleSend={() => handleSubmitQuery()}
              showMetricDropdown={showMetricDropdown}
              filteredMetrics={filteredMetrics}
              selectMetric={selectMetric}
              showSkillDropdown={showSkillDropdown}
              filteredSkills={filteredSkills}
              selectSkill={selectSkill}
              showReportDropdown={showReportDropdown}
              filteredReports={filteredReports}
              selectReport={selectReport}
              setActiveLineage={setActiveLineage}
              setShowLineageDrawer={setShowLineageDrawer}
              openMetricDrawerById={openMetricDrawerById}
              onClarifySubmit={handleClarificationSubmit}
              onCorrectSubmit={handleCorrectionSubmit}
              onSaveMetric={handleSaveExplorationAsMetric}
              isHarnessMode={isHarnessMode}
              setIsHarnessMode={setIsHarnessMode}
              onHarnessClarifySubmit={handleHarnessClarifySubmit}
              onHarnessConfirmSubmit={handleHarnessConfirmSubmit}
              onHarnessCancel={handleHarnessCancel}
              currentUserId={userContext.user_id}
              onAdoptGap={(dsId, spaceId, fieldId) => {
                setSelectedProfileDsId(dsId);
                setSelectedSpaceId(spaceId);
                setPreSelectedFieldId(fieldId);
                setActiveTab('sources');
              }}
            />
          )}

          {/* Custom Workspace Panel */}
          {activeTab === 'workspace' && (
            initialDataLoaded ? <AssetWorkspace
              metrics={metrics}
              skills={skills}
              reports={reports}
              fields={fields}
              dataSources={dataSources}
              userContext={userContext}
              darkMode={darkMode}
              onRefreshAll={refreshAllData}
              onPreviewMetric={openMetricDrawer}
              onPreviewReport={openEditReport}
            /> : <PageLoadingState label="正在加载个人空间…" />
          )}

          {/* Packs Panel */}
          {activeTab === 'packs' && (
            <div className="relative flex-1 flex flex-col min-h-0 bg-white dark:bg-slate-950 text-left">
              <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
                {packsTab === 'list' ? (
                  <PackProducts
                    metrics={metrics}
                    skills={skills}
                    reports={reports}
                    userContext={userContext}
                    onRefreshData={refreshAllData}
                    onPreviewMetric={openMetricDrawer}
                    onPreviewReport={openEditReport}
                    onEditEnterprisePack={setEditingPack}
                    onOpenMounting={(deploymentId) => {
                      setActiveDeploymentId(deploymentId);
                      setPacksTab('mounting');
                    }}
                    activeDataSourceId={activeDataSourceId}
                  />
                ) : (
                  <PackDeploymentWorkbench
                    userContext={userContext}
                    dataSources={dataSources}
                    initialDeploymentId={activeDeploymentId}
                    onBack={() => { setPacksTab('list'); setActiveDeploymentId(null); }}
                  />
                )}
                {editingPack && (
                  <div className="absolute inset-0 z-20 overflow-hidden bg-slate-50 dark:bg-slate-950">
                    <PackEditor
                      pack={editingPack}
                      userContext={userContext}
                      onClose={() => setEditingPack(null)}
                      onRefreshPack={setEditingPack}
                    />
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Data Sources Connection Panel / Space Workbench */}
          {activeTab === 'sources' && (
            selectedSpaceId ? (
              <SemanticProfileViewer
                dsId={selectedProfileDsId}
                spaceId={selectedSpaceId}
                isAdmin={isSystemAdmin}
                onBack={() => {
                  setFocusSemanticSpace({
                    dsId: selectedProfileDsId,
                    spaceId: selectedSpaceId,
                    nonce: Date.now()
                  });
                  setPreSelectedFieldId(null);
                  setSelectedSpaceId(null);
                }}
                preSelectedFieldId={preSelectedFieldId}
              />
            ) : (
              <DataSourceManager
                dataSources={dataSources}
                isSystemAdmin={isSystemAdmin}
                onRefreshSources={refreshSources}
                onViewProfile={(dsId) => {
                  setSelectedProfileDsId(dsId);
                  setSelectedSpaceId(`space_default_${dsId}`);
                }}
                onOpenSpace={(dsId, spaceId) => {
                  const params = new URLSearchParams();
                  params.set('tab', 'sources');
                  params.set('dsId', dsId);
                  params.set('spaceId', spaceId);
                  const nextHash = params.toString();
                  if (window.location.hash.slice(1) !== nextHash) {
                    window.history.pushState(null, '', `${window.location.pathname}${window.location.search}#${nextHash}`);
                  }
                  setSelectedProfileDsId(dsId);
                  setSelectedSpaceId(spaceId);
                }}
                focusSemanticSpace={focusSemanticSpace}
              />
            )
          )}

          {activeTab === 'settings' && (
            <SystemSettingsPage
              userContext={userContext}
              llmSettings={llmSettings}
              llmBaseUrl={llmBaseUrl}
              setLlmBaseUrl={setLlmBaseUrl}
              llmModel={llmModel}
              setLlmModel={setLlmModel}
              llmApiKey={llmApiKey}
              setLlmApiKey={setLlmApiKey}
              llmTimeout={llmTimeout}
              setLlmTimeout={setLlmTimeout}
              isSavingLlm={isSavingLlm}
              isProbingLlm={isProbingLlm}
              llmProbe={llmProbe}
              onSaveLlm={handleSaveLlmSettings}
              onProbeLlm={() => void handleProbeLlm()}
              managedUsers={managedUsers}
              onCreateUser={openCreateUser}
              onEditUser={openEditUser}
              onRoleChange={(username, role) => void handleUserRoleChange(username, role)}
              onDeleteUser={username => void handleDeleteManagedUser(username)}
              userModalOpen={newUserModalOpen}
              editingUsername={editingUsername}
              userDraft={newUser}
              setUserDraft={setNewUser}
              isSavingUser={isSavingUser}
              onSaveUser={handleCreateManagedUser}
              onCloseUserModal={() => { setNewUserModalOpen(false); setEditingUsername(null); }}
            />
          )}

          </Suspense>

        </main>
      </div>

      {/* 4. Lineage Inspector Drawer */}
      {showLineageDrawer && activeLineage && (
        <div className="fixed inset-0 bg-slate-900/40 dark:bg-slate-950/60 backdrop-blur-xs flex justify-end z-30 transition-all">
          <div className="w-96 max-w-full bg-white dark:bg-slate-900 h-full shadow-2xl p-6 overflow-y-auto space-y-6 flex flex-col justify-between text-left">
            <div className="space-y-6">
              <div className="flex justify-between items-center pb-4 border-b border-slate-100 dark:border-slate-800">
                <div>
                  <h3 className="font-bold text-slate-900 dark:text-white text-sm">数据源血缘追溯 (Lineage)</h3>
                  <span className="text-[10px] text-slate-400 font-mono">溯源 ID: {activeLineage.lineage_id}</span>
                </div>
                <button
                  onClick={() => setShowLineageDrawer(false)}
                  className="text-slate-400 hover:text-slate-650 font-bold"
                >
                  ✕
                </button>
              </div>

              {/* Data tracing list */}
              <div className="space-y-4 text-xs">
                <div>
                  <strong className="text-[10px] text-slate-400 uppercase tracking-wider block mb-1">源头业务系统 Source System</strong>
                  <span className="bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200 px-2.5 py-1 rounded font-mono font-bold">
                    {activeLineage.source_system}
                  </span>
                </div>

                <div>
                  <strong className="text-[10px] text-slate-400 uppercase tracking-wider block mb-1">数据库连接配置 Database ID</strong>
                  <span className="bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200 px-2.5 py-1 rounded font-mono">
                    {activeLineage.data_source_id}
                  </span>
                </div>

                <div>
                  <strong className="text-[10px] text-slate-400 uppercase tracking-wider block mb-1">物理数据表 Physical Tables</strong>
                  <div className="flex flex-wrap gap-1 mt-1 font-mono">
                    {activeLineage.physical_tables.map((t: string) => (
                      <span key={t} className="bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-800 px-2 py-0.5 rounded">
                        {t}
                      </span>
                    ))}
                  </div>
                </div>

                <div>
                  <strong className="text-[10px] text-slate-400 uppercase tracking-wider block mb-1">计算中涉及的指标与版本 Metric Catalog Versions</strong>
                  <div className="space-y-1 mt-1">
                    {activeLineage.metric_codes.map((mc: string) => (
                      <div key={mc} className="flex justify-between font-mono bg-slate-50 dark:bg-slate-800 p-2 rounded">
                        <span>{mc}</span>
                        <span className="text-slate-400">v{activeLineage.metric_versions[mc] || '1.0.0'}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  <strong className="text-[10px] text-slate-400 uppercase tracking-wider block mb-1">逻辑公式摘要 Logical Expression</strong>
                  <div className="bg-slate-50 dark:bg-slate-800 p-3 rounded-lg border border-slate-100 dark:border-slate-800 font-mono break-all">
                    {activeLineage.formula_summary || '动态 SQL 解析模板，无独立固化公式'}
                  </div>
                </div>
              </div>
            </div>

            <div className="border-t border-slate-100 dark:border-slate-800 pt-4 text-[9px] text-slate-400">
              数据中心已于 {activeLineage.executed_at ? new Date(activeLineage.executed_at).toLocaleString() : new Date().toLocaleString()} 验证完毕，数据真实无篡改。
            </div>
          </div>
        </div>
      )}

      {/* 5. Metric Detail Drawer */}
      {showMetricDrawer && selectedMetric && (
        <div
          className="fixed inset-0 bg-slate-900/40 dark:bg-slate-950/60 backdrop-blur-xs flex justify-end z-40"
          onClick={() => setShowMetricDrawer(false)}
        >
          <div
            className="w-96 max-w-full bg-white dark:bg-slate-900 h-full shadow-2xl p-6 overflow-y-auto space-y-6 text-left"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex justify-between items-start gap-4 pb-4 border-b border-slate-100 dark:border-slate-800">
              <div>
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="px-2 py-0.5 rounded bg-indigo-50 dark:bg-indigo-950/20 text-indigo-650 dark:text-indigo-400 text-[8px] font-bold">官方预置</span>
                  <span className="text-[10px] text-slate-400">v{selectedMetric.version || '1.0.0'}</span>
                </div>
                <h3 className="text-base font-bold text-slate-850 dark:text-white">{selectedMetric.name}</h3>
                <p className="text-[10px] font-mono text-slate-400 break-all mt-1">{selectedMetric.metric_code}</p>
              </div>
              <button onClick={() => setShowMetricDrawer(false)} className="text-slate-400 hover:text-slate-650"><X className="w-5 h-5" /></button>
            </div>

            <div className="space-y-4 text-xs">
              <div>
                <span className="text-[10px] text-slate-400 uppercase tracking-wider block mb-1">指标业务口径</span>
                <p className="text-slate-700 dark:text-slate-350 leading-relaxed bg-slate-50 dark:bg-slate-800/30 p-3 rounded-lg border border-slate-100 dark:border-slate-800">{selectedMetric.definition}</p>
              </div>

              <div>
                <span className="text-[10px] text-slate-400 uppercase tracking-wider block mb-1">公式定义 (Logical Formula)</span>
                <pre className="p-3 rounded-lg bg-slate-50 dark:bg-slate-900 border border-slate-100 dark:border-slate-800 font-mono text-[10px] text-slate-600 dark:text-slate-400 whitespace-pre-wrap select-all">{selectedMetric.formula.expression}</pre>
              </div>

              {metricDependencies.length > 0 && (
                <div>
                  <span className="text-[10px] text-slate-400 uppercase tracking-wider block mb-1">关联计算物理列</span>
                  <div className="space-y-1 mt-1 font-mono text-[10px] text-slate-600">
                    {metricDependencies.map(dep => (
                      <div key={dep.source_id} className="flex justify-between bg-slate-50 dark:bg-slate-800 p-2 rounded">
                        <span>{dep.source_name} ({dep.source_id})</span>
                        <span className="text-slate-400">{dep.relation_type}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

    </div>
  );
}

const openEditReport = (report: ReportDefinition) => {
  window.alert(`如需修改官方报表 "${report.name}"，请先点击其卡片上的「另存为我的报表」生成私有副本。`);
};
