/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Alert, Form, Spin, Switch} from 'antd';
import styles from './index.module.css';
import http from 'libs/http';
import store from './store';

export default observer(function () {
  function handleChangeVerifyIP(v) {
    store.isFetching = true;
    http.post('/api/setting/', {data: [{key: 'verify_ip', value: v}]})
      .then(() => store.fetchSettings(), () => store.isFetching = false)
  }

  function handleChangeBindIP(v) {
    store.isFetching = true;
    http.post('/api/setting/', {data: [{key: 'bind_ip', value: v}]})
      .then(() => store.fetchSettings(), () => store.isFetching = false)
  }

  const {verify_ip, bind_ip} = store.settings;
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
        <Alert
          showIcon
          type="info"
          message="MFA 已改为账号独立设置"
          description="每个账号可在个人中心的“身份认证器”中自行开启或关闭 MFA。"/>
      </Form>
    </Spin>
  )
})
