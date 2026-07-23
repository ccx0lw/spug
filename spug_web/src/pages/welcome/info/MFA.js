/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, {useEffect, useState} from 'react';
import {observer} from 'mobx-react';
import {Alert, Button, Form, Input, Modal, Space, Spin, Typography, message} from 'antd';
import {http} from 'libs';
import styles from './index.module.css';
import store from './store';


export default observer(function MFA() {
  const [fetching, setFetching] = useState(false);
  const [loading, setLoading] = useState(false);
  const [setup, setSetup] = useState();
  const [code, setCode] = useState();
  const [action, setAction] = useState();
  const [actionCode, setActionCode] = useState();

  useEffect(() => {
    setFetching(true);
    store.fetchUser().finally(() => setFetching(false))
  }, []);

  function handleCreateSetup() {
    setLoading(true);
    http.get('/api/account/mfa/')
      .then(data => {
        setSetup(data);
        setCode(undefined)
      })
      .finally(() => setLoading(false))
  }

  function handleBind() {
    if (!code || code.length !== 6) return message.error('请输入6位验证码');
    setLoading(true);
    http.post('/api/account/mfa/', {
      action: 'bind',
      code,
      setup_token: setup.setup_token,
    }).then(() => {
      message.success('MFA 已开启');
      setSetup(undefined);
      setCode(undefined);
      return store.fetchUser()
    }).finally(() => setLoading(false))
  }

  function handleAction() {
    if (!actionCode || actionCode.length !== 6) return message.error('请输入6位验证码');
    setLoading(true);
    http.post('/api/account/mfa/', {action, code: actionCode})
      .then(() => {
        const messages = {
          enable: 'MFA 已开启',
          disable: 'MFA 已关闭',
          unbind: '身份认证器已解除绑定',
        };
        message.success(messages[action]);
        setAction(undefined);
        setActionCode(undefined);
        return store.fetchUser()
      })
      .finally(() => setLoading(false))
  }

  const actionTitles = {
    enable: '开启 MFA',
    disable: '关闭 MFA',
    unbind: '解除身份认证器绑定',
  };

  return (
    <Spin spinning={fetching}>
      <div className={styles.title}>身份认证器</div>
      <div style={{maxWidth: 520}}>
        <Alert
          showIcon
          type="info"
          message="MFA 由每个账号独立设置"
          description="开启后，登录以及 Web 终端、执行命令、文件分发等敏感操作都需要使用身份认证器验证码。"
          style={{marginBottom: 24}}/>
        {store.user.mfa_bound ? (
          <React.Fragment>
            <Alert
              showIcon
              type={store.user.mfa_enabled ? 'success' : 'warning'}
              message={store.user.mfa_enabled ?
                '当前账户已开启 MFA' :
                '当前账户 MFA 已关闭，身份认证器仍保持绑定'}/>
            <Space style={{marginTop: 24}}>
              {store.user.mfa_enabled ? (
                <Button danger onClick={() => setAction('disable')}>关闭 MFA</Button>
              ) : (
                <Button type="primary" onClick={() => setAction('enable')}>开启 MFA</Button>
              )}
              <Button onClick={() => setAction('unbind')}>解除身份认证器绑定</Button>
            </Space>
          </React.Fragment>
        ) : setup ? (
          <div style={{textAlign: 'center'}}>
            <div style={{marginBottom: 8, fontWeight: 500}}>1. 扫描二维码</div>
            <img src={setup.qr_code} alt="身份认证器二维码" style={{width: 220, height: 220}}/>
            <div style={{marginTop: 8}}>
              无法扫码时手动输入：<Typography.Text copyable>{setup.secret}</Typography.Text>
            </div>
            <div style={{marginTop: 24, marginBottom: 8, fontWeight: 500}}>2. 输入认证器显示的6位验证码</div>
            <Input
              value={code}
              maxLength={6}
              autoComplete="off"
              placeholder="请输入6位验证码"
              style={{width: 220}}
              onChange={e => setCode(e.target.value)}/>
            <div style={{marginTop: 16}}>
              <Button onClick={() => setSetup(undefined)}>取消</Button>
              <Button type="primary" loading={loading} style={{marginLeft: 12}} onClick={handleBind}>确认绑定</Button>
            </div>
          </div>
        ) : (
          <Button type="primary" loading={loading} onClick={handleCreateSetup}>开启 MFA</Button>
        )}
      </div>

      <Modal
        visible={Boolean(action)}
        title={actionTitles[action]}
        okText="确认"
        okButtonProps={{danger: action !== 'enable'}}
        confirmLoading={loading}
        onOk={handleAction}
        onCancel={() => {
          setAction(undefined);
          setActionCode(undefined)
        }}>
        <Alert
          showIcon
          type={action === 'enable' ? 'info' : 'warning'}
          message={action === 'enable' ?
            '开启后，下次登录和敏感操作将要求 MFA 验证。' :
            action === 'disable' ?
              '关闭后登录不再要求 MFA；Web 终端、执行命令和文件分发将不可使用。' :
              '解除绑定会同时关闭 MFA，再次开启时需要重新扫描二维码。'}
          style={{marginBottom: 16}}/>
        <Form layout="vertical">
          <Form.Item required label="当前验证码">
            <Input
              value={actionCode}
              maxLength={6}
              autoComplete="off"
              placeholder="请输入身份认证器中的6位验证码"
              onChange={e => setActionCode(e.target.value)}/>
          </Form.Item>
        </Form>
      </Modal>
    </Spin>
  )
})
