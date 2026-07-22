/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, {useState, useEffect} from 'react';
import {observer} from 'mobx-react';
import {Alert, Button, Form, Input, Select, Space, Spin, Switch, Typography, message} from 'antd';
import styles from './index.module.css';
import http from 'libs/http';
import store from './store';

export default observer(function () {
  const [code, setCode] = useState();
  const [visible, setVisible] = useState(false);
  const [counter, setCounter] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loading2, setLoading2] = useState(false);
  const [selectedMethod, setMethod] = useState();
  const [totpSetup, setTotpSetup] = useState();

  useEffect(() => {
    if (counter <= 0) return;
    const timer = setTimeout(() => setCounter(counter - 1), 1000);
    return () => clearTimeout(timer)
  }, [counter])

  function handleChangeVerifyIP(v) {
    store.isFetching = true;
    http.post('/api/setting/', {data: [{key: 'verify_ip', value: v}]})
      .then(() => {
        message.success('设置成功');
        store.fetchSettings()
      }, () => store.isFetching = false)
  }

  function handleChangeBindIP(v) {
    store.isFetching = true;
    http.post('/api/setting/', {data: [{key: 'bind_ip', value: v}]})
      .then(() => {
        message.success('设置成功');
        store.fetchSettings()
      }, () => store.isFetching = false)
  }

  function handleChangeMFA(v) {
    if (v && method === 'push' && !store.settings.spug_push_key) {
      return message.error('开启推送MFA需要先在推送服务设置中绑定推送助手账户')
    }
    setCode(undefined);
    setTotpSetup(undefined);
    if (!v) return handleMFAModify(false)
    setVisible(true);
    if (method === 'totp') {
      setLoading(true);
      http.get('/api/setting/mfa/', {params: {method: 'totp'}})
        .then(setTotpSetup)
        .catch(() => setVisible(false))
        .finally(() => setLoading(false))
    }
  }

  function handleCaptcha() {
    setLoading(true)
    http.get('/api/setting/mfa/')
      .then(() => setCounter(60))
      .finally(() => setLoading(false))
  }

  function handleMFAModify(v) {
    setLoading2(true)
    const data = {enable: v, method, code};
    if (totpSetup?.setup_token) data.setup_token = totpSetup.setup_token;
    http.post('/api/setting/mfa/', data)
      .then(() => {
        setVisible(false);
        setCode(undefined);
        setTotpSetup(undefined);
        message.success('设置成功');
        store.fetchSettings()
      })
      .finally(() => setLoading2(false))
  }

  const {verify_ip, bind_ip, MFA} = store.settings;
  const method = selectedMethod || MFA?.method || 'push';
  return (
    <Spin spinning={store.isFetching}>
      <div className={styles.title}>安全设置</div>
      <Form layout="vertical" style={{maxWidth: 500}}>
        <Form.Item
          label="访问IP校验"
          extra={<span>建议开启，校验是否获取了真实的访问者IP，防止因为增加的反向代理层导致基于IP的安全策略失效，当校验失败时会在登录时弹窗提醒。如果你在内网部署且仅在内网使用可以关闭该特性。<a
            href="https://spug.cc/docs/practice"
            target="_blank" rel="noopener noreferrer">为什么没有获取到真实IP？</a></span>}>
          <Switch
            checkedChildren="开启"
            unCheckedChildren="关闭"
            onChange={handleChangeVerifyIP}
            checked={verify_ip}/>
        </Form.Item>
        <Form.Item
          label="登录IP绑定"
          extra="强烈建议开启，当开启后会把登录凭证与IP进行绑定，当该登录凭证通过其他IP访问时将自动失效。如非必要，切勿关闭该特性！">
          <Switch
            checkedChildren="开启"
            unCheckedChildren="关闭"
            onChange={handleChangeBindIP}
            checked={bind_ip}/>
        </Form.Item>
        <Form.Item
          label="MFA认证方式"
          style={{marginTop: 24}}
          extra={MFA?.enable ? '切换认证方式前请先关闭登录MFA。' : '推送验证码兼容原有流程；身份认证器支持 Google Authenticator 等 TOTP 应用。'}>
          <Select
            value={method}
            disabled={MFA?.enable}
            style={{width: 240}}
            onChange={v => {
              setMethod(v);
              setVisible(false);
              setCode(undefined);
              setTotpSetup(undefined)
            }}>
            <Select.Option value="push">推送验证码</Select.Option>
            <Select.Option value="totp">身份认证器（TOTP）</Select.Option>
          </Select>
        </Form.Item>
        <Form.Item
          label="登录MFA（两步）认证"
          extra={visible ? '输入验证码，通过验证后开启。' :
            method === 'totp' ?
              '首次开启会展示二维码完成身份认证器绑定；其他未绑定账户会在首次登录时完成绑定。' :
              <span>建议开启，登录时额外使用推送验证码进行身份验证。开启前请确保账户已配置推送MFA标识。<a
                target="_blank" rel="noopener noreferrer"
                href="https://push.spug.cc/guide/spug">配置手册</a></span>}>
          {visible ? (
            <div style={{width: 490}}>
              <Spin spinning={loading}>
                {method === 'totp' && totpSetup && !totpSetup.mfa_bound ? (
                  <div style={{textAlign: 'center', marginBottom: 20}}>
                    <Alert
                      showIcon
                      type="info"
                      message="请使用 Google Authenticator 或其他兼容 TOTP 的应用扫描二维码。"
                      style={{textAlign: 'left', marginBottom: 12}}/>
                    <div style={{marginBottom: 8, fontWeight: 500}}>1. 扫描二维码</div>
                    <img
                      src={totpSetup.qr_code}
                      alt="身份认证器二维码"
                      style={{width: 220, height: 220}}/>
                    <div style={{marginTop: 8}}>
                      无法扫码时手动输入：
                      <Typography.Text copyable>{totpSetup.secret}</Typography.Text>
                    </div>
                    <div style={{marginTop: 20, marginBottom: 8, fontWeight: 500}}>
                      2. 输入认证器显示的6位验证码
                    </div>
                  </div>
                ) : null}
                <div style={{display: 'flex'}}>
                  <Input
                    value={code}
                    maxLength={6}
                    autoComplete="off"
                    placeholder={method === 'totp' ? '请输入身份认证器中的6位验证码' : '请输入验证码'}
                    onChange={e => setCode(e.target.value)}/>
                  {method === 'push' ? counter > 0 ? (
                    <Button disabled style={{marginLeft: 8}}>{counter} 秒后重新获取</Button>
                  ) : (
                    <Button loading={loading} style={{marginLeft: 8}} onClick={handleCaptcha}>获取验证码</Button>
                  ) : null}
                </div>
                <Space style={{marginTop: 12}}>
                  <Button onClick={() => {
                    setVisible(false);
                    setTotpSetup(undefined)
                  }}>取消</Button>
                  <Button
                    type="primary"
                    loading={loading2}
                    disabled={loading || (method === 'totp' && !totpSetup)}
                    onClick={() => handleMFAModify(true)}>确认</Button>
                </Space>
              </Spin>
            </div>
          ) : (
            <Switch
              checkedChildren="开启"
              unCheckedChildren="关闭"
              onChange={handleChangeMFA}
              checked={MFA?.enable}/>
          )}
        </Form.Item>
      </Form>
    </Spin>
  )
})
