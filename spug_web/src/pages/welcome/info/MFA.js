/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, {useEffect, useState} from 'react';
import {observer} from 'mobx-react';
import {Alert, Button, Form, Input, Modal, Spin, Typography, message} from 'antd';
import {http} from 'libs';
import styles from './index.module.css';
import store from './store';


export default observer(function MFA() {
  const [fetching, setFetching] = useState(false);
  const [loading, setLoading] = useState(false);
  const [setup, setSetup] = useState();
  const [code, setCode] = useState();
  const [unbindVisible, setUnbindVisible] = useState(false);
  const [unbindCode, setUnbindCode] = useState();

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
      message.success('身份认证器绑定成功');
      setSetup(undefined);
      setCode(undefined);
      return store.fetchUser()
    }).finally(() => setLoading(false))
  }

  function handleUnbind() {
    if (!unbindCode || unbindCode.length !== 6) return message.error('请输入6位验证码');
    setLoading(true);
    http.post('/api/account/mfa/', {action: 'unbind', code: unbindCode})
      .then(() => {
        message.success('身份认证器已解除绑定');
        setUnbindVisible(false);
        setUnbindCode(undefined);
        return store.fetchUser()
      })
      .finally(() => setLoading(false))
  }

  return (
    <Spin spinning={fetching}>
      <div className={styles.title}>身份认证器</div>
      <div style={{maxWidth: 520}}>
        <Alert
          showIcon
          type="info"
          message="使用 Google Authenticator 或其他兼容 TOTP 的应用生成登录验证码。"
          style={{marginBottom: 24}}/>
        {store.user.mfa_bound ? (
          <React.Fragment>
            <Alert showIcon type="success" message="当前账户已绑定身份认证器"/>
            <Button danger style={{marginTop: 24}} onClick={() => setUnbindVisible(true)}>解除绑定</Button>
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
          <Button type="primary" loading={loading} onClick={handleCreateSetup}>绑定身份认证器</Button>
        )}
      </div>

      <Modal
        visible={unbindVisible}
        title="解除身份认证器绑定"
        okText="确认解除"
        okButtonProps={{danger: true}}
        confirmLoading={loading}
        onOk={handleUnbind}
        onCancel={() => {
          setUnbindVisible(false);
          setUnbindCode(undefined)
        }}>
        <Alert
          showIcon
          type="warning"
          message="解除后，如果系统要求使用身份认证器，下次登录时需要重新绑定。"
          style={{marginBottom: 16}}/>
        <Form layout="vertical">
          <Form.Item required label="当前验证码">
            <Input
              value={unbindCode}
              maxLength={6}
              autoComplete="off"
              placeholder="请输入身份认证器中的6位验证码"
              onChange={e => setUnbindCode(e.target.value)}/>
          </Form.Item>
        </Form>
      </Modal>
    </Spin>
  )
})
