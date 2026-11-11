import { useEffect, useRef, useState } from 'react';
import { LogIn } from 'lucide-react';
import {
  Button,
  Input,
  Label,
  ListBox,
  Drawer,
  ProgressBar,
  Select,
  TextArea,
  TextField,
} from '@heroui/react';
import { copyText } from '../lib/clipboard';
import {
  FileUpload,
  type FileUploadItem,
} from './motion/file-upload';
import type { Account } from '../lib/types';
import { CheckIcon, CopyIcon, UploadIcon } from './icons';

const MAX_BYTES = 300 * 1024 * 1024;
const REFERENCE_MAX_BYTES = 12 * 1024 * 1024;
const AUDIO_FILE_RE = /\.(wav|mp3|flac|m4a|ogg|aac)$/i;

const LANGUAGES = [
  { value: 'none', label: '未指定' },
  { value: 'zh', label: '中文' },
  { value: 'ja', label: '日语' },
  { value: 'en', label: '英语' },
  { value: 'ko', label: '韩语' },
  { value: 'other', label: '其他' },
];

const GENDERS = [
  { value: 'none', label: '未指定' },
  { value: 'female', label: '女声' },
  { value: 'male', label: '男声' },
  { value: 'neutral', label: '中性' },
];

export type Submission = {
  id?: string;
  status?: string;
  name?: string;
  reason?: string;
  visibility?: string;
};

type UploadDrawerProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  account: Account | null;
};

function ShareRow({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    if (await copyText(value)) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    }
  };

  return (
    <div className="flex items-center gap-2 rounded-xl border border-border bg-surface-secondary/60 px-3 py-2">
      <span className="shrink-0 text-[11px] text-muted">{label}</span>
      <code className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-foreground">
        {value}
      </code>
      <Button
        aria-label={`复制${label}`}
        className="shrink-0 gap-1"
        onPress={copy}
        size="sm"
        variant="ghost"
      >
        {copied ? (
          <>
            <CheckIcon className="size-3 text-accent" />
            已复制
          </>
        ) : (
          <>
            <CopyIcon className="size-3" />
            复制
          </>
        )}
      </Button>
    </div>
  );
}

export function UploadDrawer({ open, onOpenChange, account }: UploadDrawerProps) {
  const [label, setLabel] = useState('');
  const [engine, setEngine] = useState<'rvc' | 'svc_ref'>('rvc');
  const [clipSeconds, setClipSeconds] = useState<number | null>(null);
  const [consent, setConsent] = useState(false);
  const [description, setDescription] = useState('');
  const [language, setLanguage] = useState('none');
  const [gender, setGender] = useState('none');
  const [tags, setTags] = useState('');
  const [mode, setMode] = useState<'file' | 'url'>('file');
  const [file, setFile] = useState<File | null>(null);
  const [uploadItems, setUploadItems] = useState<FileUploadItem[]>([]);
  const [url, setUrl] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState('');
  const [result, setResult] = useState<Submission | null>(null);
  const [publishing, setPublishing] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open && result) {
      setResult(null);
      setError('');
      setProgress(0);
    }
  }, [open, result]);

  const reset = () => {
    setLabel('');
    setEngine('rvc');
    setClipSeconds(null);
    setConsent(false);
    setDescription('');
    setLanguage('none');
    setGender('none');
    setTags('');
    setMode('file');
    setFile(null);
    setUploadItems([]);
    setUrl('');
    setError('');
    setProgress(0);
    setResult(null);
    if (fileRef.current) fileRef.current.value = '';
  };

  const handleOpenChange = (next: boolean) => {
    if (!next && submitting) return;
    onOpenChange(next);
  };

  const chooseEngine = (next: 'rvc' | 'svc_ref') => {
    if (engine === next) return;
    setEngine(next);
    setMode('file');
    setFile(null);
    setUploadItems([]);
    setUrl('');
    setClipSeconds(null);
    setConsent(false);
    setError('');
  };

  const inspectClip = (nextFile: File | null) => {
    setClipSeconds(null);
    setError('');
    if (!nextFile) return;
    const audio = document.createElement('audio');
    const objectUrl = URL.createObjectURL(nextFile);
    const cleanup = () => URL.revokeObjectURL(objectUrl);
    audio.preload = 'metadata';
    audio.onloadedmetadata = () => {
      cleanup();
      const seconds = audio.duration;
      if (!Number.isFinite(seconds)) return;
      setClipSeconds(seconds);
      if (seconds < 5) {
        setError(`参考音频太短（${seconds.toFixed(1)} 秒），至少需要 5 秒`);
      }
    };
    audio.onerror = () => {
      cleanup();
      setError('无法读取这段音频，请换一个可播放的文件');
    };
    audio.src = objectUrl;
  };

  const validate = (): boolean => {
    if (!label.trim()) {
      setError('请填写音色显示名');
      return false;
    }
    if (mode === 'file') {
      if (!file) {
        setError(engine === 'svc_ref' ? '请选择参考音频文件' : '请选择要上传的 zip 文件');
        return false;
      }
      if (engine === 'svc_ref') {
        if (!AUDIO_FILE_RE.test(file.name)) {
          setError('参考音频仅支持 wav / mp3 / flac / m4a / ogg / aac');
          return false;
        }
        if (file.size > REFERENCE_MAX_BYTES) {
          setError('参考音频超过 12MB 上限');
          return false;
        }
        if (clipSeconds !== null && clipSeconds < 5) {
          setError('参考音频太短，至少需要 5 秒连续清唱');
          return false;
        }
      } else {
        if (!/\.zip$/i.test(file.name)) {
          setError('仅支持 .zip 文件');
          return false;
        }
        if (file.size > MAX_BYTES) {
          setError('文件超过 300MB 上限');
          return false;
        }
      }
    } else if (!/^https?:\/\//i.test(url.trim())) {
      setError('请填写 http/https 直链');
      return false;
    }
    if (engine === 'svc_ref' && !consent) {
      setError('请确认你拥有这段录音的使用权');
      return false;
    }
    setError('');
    return true;
  };

  const submit = () => {
    if (submitting || !validate()) return;

    const body = new FormData();
    body.append('engine', engine);
    if (engine === 'svc_ref') body.append('consent', consent ? '1' : '0');
    body.append('label', label.trim());
    body.append('description', description.trim());
    body.append('language', language === 'none' ? '' : language);
    body.append('gender', gender === 'none' ? '' : gender);
    body.append('tags', tags.trim());
    if (mode === 'file' && file) body.append('file', file);
    else body.append('url', url.trim());

    setSubmitting(true);
    setProgress(0);
    setUploadItems((current) =>
      current.map((item) => ({ ...item, status: 'uploading' as const, progress: 0 })),
    );
    setError('');
    setResult(null);

    const request = new XMLHttpRequest();
    request.open('POST', '/v1/voice-requests');
    request.responseType = 'json';
    request.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) {
        const percent = Math.round((event.loaded / event.total) * 100);
        setProgress(percent);
        setUploadItems((current) =>
          current.map((item) => ({ ...item, progress: percent })),
        );
      }
    });
    request.addEventListener('load', () => {
      setSubmitting(false);
      const payload = request.response as Submission | null;
      if (request.status === 401) {
        setError('登录已过期，请重新登录后提交。');
        return;
      }
      if (request.status >= 200 && request.status < 300 && payload) {
        setUploadItems((current) =>
          current.map((item) => ({ ...item, status: 'success' as const, progress: 100 })),
        );
        setResult(payload);
        return;
      }
      setUploadItems((current) =>
        current.map((item) => ({ ...item, status: 'error' as const })),
      );
      const detail = (payload as { detail?: string } | null)?.detail;
      setError(detail ? String(detail) : `提交失败（HTTP ${request.status}）`);
    });
    request.addEventListener('error', () => {
      setSubmitting(false);
      setUploadItems((current) =>
        current.map((item) => ({ ...item, status: 'error' as const })),
      );
      setError('网络错误，请稍后重试。');
    });
    request.send(body);
  };

  const publish = async () => {
    if (!result?.id || publishing) return;
    setPublishing(true);
    try {
      const response = await fetch(
        `/v1/voice-requests/${encodeURIComponent(result.id)}/publish`,
        { method: 'POST' },
      );
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(payload?.detail || `HTTP ${response.status}`);
      }
      setResult((current) => ({
        ...(current ?? {}),
        ...(payload?.submission ?? {}),
        visibility: 'public',
      }));
    } catch (publishError) {
      setError(
        `公开失败：${publishError instanceof Error ? publishError.message : '请稍后重试'}`,
      );
    } finally {
      setPublishing(false);
    }
  };

  const approved = result?.status === 'approved';
  const isPublic = result?.visibility === 'public';

  return (
    <Drawer>
      <Drawer.Backdrop isOpen={open} onOpenChange={handleOpenChange}>
        <Drawer.Content placement="right">
          <Drawer.Dialog className="w-full max-w-[460px]">
            <Drawer.CloseTrigger />
            <Drawer.Header>
              <Drawer.Heading className="text-[16px]">上传音色</Drawer.Heading>
            </Drawer.Header>

            <Drawer.Body className="gap-4">
              {!account ? (
                <div className="space-y-3 py-1">
                  <p className="text-[13.5px] font-semibold">
                    上传音色需要先登录 FlowBee 账号
                  </p>
                  <p className="text-[12.5px] leading-relaxed text-muted">
                    登录后提交的音色会绑定到你的账号，可以在「我的音色」里查看状态、复制音色名或公开到广场。
                  </p>
                  <Button
                    className="gap-1.5 !bg-foreground !text-background hover:!bg-foreground/85"
                    onPress={() => {
                      window.location.href = '/v1/auth/login?next=/upload.html';
                    }}
                  >
                    <LogIn className="size-4" strokeWidth={1.75} />
                    使用 FlowBee 账号登录
                  </Button>
                </div>
              ) : result ? (
                <div className="space-y-3 py-1">
                  <div>
                    <p
                      className={`text-[14px] font-semibold ${approved ? 'text-accent' : 'text-danger'}`}
                    >
                      {approved
                        ? engine === 'svc_ref'
                          ? '参考音色已可用（无需训练）'
                          : '审核通过，音色已可用'
                        : '未通过审核'}
                    </p>
                    {result.reason && (
                      <p className="mt-1 text-[12.5px] leading-relaxed text-muted">
                        {result.reason}
                      </p>
                    )}
                  </div>

                  {approved && result.name && (
                    <>
                      <ShareRow label="音色名" value={result.name} />
                      <ShareRow
                        label="分享文案"
                        value={`用音色 ${result.name} 唱一首《歌名》试试：/点歌 歌名 ${result.name}`}
                      />
                      <div className="flex flex-wrap items-center gap-2 pt-1">
                        {isPublic ? (
                          <span className="text-[12.5px] text-accent">
                            已公开到广场
                          </span>
                        ) : (
                          <Button
                            className="!bg-foreground !text-background hover:!bg-foreground/85"
                            isPending={publishing}
                            onPress={publish}
                            size="sm"
                            variant="secondary"
                          >
                            公开到广场
                          </Button>
                        )}
                        <a
                          className="text-[12.5px] text-accent hover:underline"
                          href="./account.html"
                        >
                          去我的音色 →
                        </a>
                      </div>
                    </>
                  )}

                  {!approved && (
                    <Button onPress={reset} size="sm" variant="secondary">
                      再试一次
                    </Button>
                  )}
                </div>
              ) : (
                <div className="space-y-4 py-1">
                  <TextField
                    isRequired
                    maxLength={80}
                    name="label"
                    onChange={setLabel}
                    value={label}
                  >
                    <Label className="text-[12.5px]">音色显示名</Label>
                    <Input placeholder="例如：我的自训练音色 / 角色名" />
                  </TextField>

                  <TextField
                    maxLength={300}
                    name="description"
                    onChange={setDescription}
                    value={description}
                  >
                    <Label className="text-[12.5px]">简介（可选）</Label>
                    <TextArea
                      className="min-h-20"
                      placeholder="这个音色适合什么歌、什么角色，或训练素材说明"
                      rows={3}
                    />
                  </TextField>

                  <div className="grid gap-3 sm:grid-cols-2">
                    <Select
                      aria-label="语言"
                      onChange={(value) => setLanguage(String(value ?? 'none'))}
                      value={language}
                    >
                      <Label className="text-[12.5px]">语言</Label>
                      <Select.Trigger className="h-9 rounded-xl">
                        <Select.Value />
                        <Select.Indicator className="text-muted" />
                      </Select.Trigger>
                      <Select.Popover>
                        <ListBox>
                          {LANGUAGES.map((item) => (
                            <ListBox.Item
                              id={item.value}
                              key={item.value}
                              textValue={item.label}
                            >
                              {item.label}
                              <ListBox.ItemIndicator />
                            </ListBox.Item>
                          ))}
                        </ListBox>
                      </Select.Popover>
                    </Select>

                    <Select
                      aria-label="声音类型"
                      onChange={(value) => setGender(String(value ?? 'none'))}
                      value={gender}
                    >
                      <Label className="text-[12.5px]">声音类型</Label>
                      <Select.Trigger className="h-9 rounded-xl">
                        <Select.Value />
                        <Select.Indicator className="text-muted" />
                      </Select.Trigger>
                      <Select.Popover>
                        <ListBox>
                          {GENDERS.map((item) => (
                            <ListBox.Item
                              id={item.value}
                              key={item.value}
                              textValue={item.label}
                            >
                              {item.label}
                              <ListBox.ItemIndicator />
                            </ListBox.Item>
                          ))}
                        </ListBox>
                      </Select.Popover>
                    </Select>
                  </div>

                  <TextField maxLength={120} name="tags" onChange={setTags} value={tags}>
                    <Label className="text-[12.5px]">标签（可选）</Label>
                    <Input placeholder="用逗号分隔，例如：初音未来, VOCALOID, 女声" />
                  </TextField>

                  <div className="space-y-2">
                    <span className="block text-[12.5px] font-medium">音色类型</span>
                    <div className="inline-flex rounded-xl border border-border bg-surface-secondary p-1">
                      <button
                        className="mode-btn"
                        data-active={engine === 'rvc'}
                        onClick={() => chooseEngine('rvc')}
                        type="button"
                      >
                        RVC 模型（.pth）
                      </button>
                      <button
                        className="mode-btn"
                        data-active={engine === 'svc_ref'}
                        onClick={() => chooseEngine('svc_ref')}
                        type="button"
                      >
                        参考音频（零样本）
                      </button>
                    </div>
                    <p className="text-[11.5px] leading-relaxed text-muted">
                      {engine === 'svc_ref'
                        ? '上传 5–30 秒单人清唱即可，不用训练；音色相似度取决于这段录音的质量。'
                        : '上传训练好的 RVC 模型 zip，声音更像，但需要自己先训练。'}
                    </p>
                    {engine === 'svc_ref' && (
                      <label className="flex items-start gap-2 text-[11.5px] leading-relaxed text-muted">
                        <input
                          checked={consent}
                          className="mt-0.5 size-3.5 shrink-0 accent-foreground"
                          onChange={(event) => setConsent(event.target.checked)}
                          type="checkbox"
                        />
                        <span>我确认有权使用这段录音，且不会用于冒充他人。</span>
                      </label>
                    )}
                  </div>

                  <div className="space-y-2">
                    <span className="block text-[12.5px] font-medium">
                      {engine === 'svc_ref' ? '音频来源' : '模型来源'}
                    </span>
                    <div className="inline-flex rounded-xl border border-border bg-surface-secondary p-1">
                      <button
                        className="mode-btn"
                        data-active={mode === 'file'}
                        onClick={() => setMode('file')}
                        type="button"
                      >
                        {engine === 'svc_ref' ? '上传音频文件' : '上传 zip 文件'}
                      </button>
                      <button
                        className="mode-btn"
                        data-active={mode === 'url'}
                        onClick={() => setMode('url')}
                        type="button"
                      >
                        {engine === 'svc_ref' ? '提供音频直链' : '提供模型直链'}
                      </button>
                    </div>

                    {mode === 'file' ? (
                      engine === 'svc_ref' ? (
                        <FileUpload
                          accept=".wav,.mp3,.flac,.m4a,.ogg,.aac,audio/*"
                          browseLabel="选择音频"
                          description="5–30 秒、单人、无伴奏、低混响；超过 30 秒只取前 30 秒。"
                          maxFiles={1}
                          onFilesAdded={(next, added) => {
                            setUploadItems(next);
                            const picked = added[0] ?? null;
                            setFile(picked);
                            inspectClip(picked);
                          }}
                          onRemove={() => {
                            setUploadItems([]);
                            setFile(null);
                            setClipSeconds(null);
                          }}
                          title="上传参考音频"
                          value={uploadItems}
                        />
                      ) : (
                        <FileUpload
                          accept=".zip,application/zip"
                          browseLabel="选择文件"
                          description="仅支持 .zip，最大 300MB；需包含 .pth 权重（.index 可选）。"
                          maxFiles={1}
                          onFilesAdded={(next, added) => {
                            setUploadItems(next);
                            setFile(added[0] ?? null);
                          }}
                          onRemove={() => {
                            setUploadItems([]);
                            setFile(null);
                          }}
                          title="上传 RVC 模型 zip"
                          value={uploadItems}
                        />
                      )
                    ) : (
                      <TextField onChange={setUrl} type="url" value={url}>
                        <Label className="sr-only">
                          {engine === 'svc_ref' ? '音频直链' : '模型直链'}
                        </Label>
                        <Input
                          placeholder={
                            engine === 'svc_ref'
                              ? 'https://example.com/reference.mp3'
                              : 'https://huggingface.co/…/resolve/main/model.zip'
                          }
                        />
                        <p className="mt-1.5 text-[11.5px] text-muted">
                          {engine === 'svc_ref'
                            ? '需要可直接播放的音频直链；服务端会下载、截取前 30 秒并重新编码。'
                            : '需要可公开下载的 zip 直链（HF / ModelScope 的 resolve 链接等）。'}
                        </p>
                      </TextField>
                    )}
                  </div>

                  {submitting && (
                    <ProgressBar aria-label="上传进度" value={progress} className="w-full">
                      <div className="mb-1 flex items-center justify-between text-[11.5px] text-muted">
                        <span>{progress >= 100 ? '上传完成，正在审核…' : '正在上传…'}</span>
                        <span className="tabular-nums">{progress}%</span>
                      </div>
                      <ProgressBar.Track>
                        <ProgressBar.Fill />
                      </ProgressBar.Track>
                    </ProgressBar>
                  )}

                  {error && (
                    <p className="rounded-xl border border-danger/25 bg-danger-soft px-3 py-2 text-[12.5px] text-danger">
                      {error}
                    </p>
                  )}
                </div>
              )}
            </Drawer.Body>

            {!result && account && (
              <Drawer.Footer>
                <Button
                  className="gap-1.5 !bg-foreground !text-background hover:!bg-foreground/85"
                  isDisabled={submitting}
                  onPress={submit}
                >
                  <UploadIcon className="size-3.5" />
                  {submitting ? '提交中…' : '提交审核'}
                </Button>
              </Drawer.Footer>
            )}
          </Drawer.Dialog>
        </Drawer.Content>
      </Drawer.Backdrop>
    </Drawer>
  );
}
