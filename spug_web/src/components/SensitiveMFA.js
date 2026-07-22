/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, {useEffect, useState} from 'react';
import {Alert, Button, Input, Modal, Spin, message} from 'antd';
import {SafetyCertificateOutlined} from '@ant-design/icons';
import {http} from 'libs';


export default function SensitiveMFA(props) {
  const [method, setMethod] = useState();
  const [code, setCode] = useState();
  const [fetching, setFetching] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [counter, setCounter] = useState(0);

  useEffect(() => {
    if (!props.visible) return;
    setMethod(undefined);
    setCode(undefined);
    setCounter(0);
    prepare();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.visible, props.scope]);

  useEffect(() => {
    if (counter <= 0) return;
    const timer = setTimeout(() => setCounter(counter - 1), 1000);
    return () => clearTimeout(timer)
  }, [counter]);

  function prepare() {
    setFetching(true);
    http.get('/api/account/mfa/sensitive/', {params: {scope: props.scope}})
      .then(data => {
        setMethod(data.method);
        if (data.method === 'push') setCounter(data.retry_after || 60)
      })
      .catch(() => props.onCancel())
      .finally(() => setFetching(false))
  }

  function handleVerify() {
    if (!/^\d{6}$/.test(code || '')) return message.error('请输入6位验证码');
    setVerifying(true);
    http.post('/api/account/mfa/sensitive/', {scope: props.scope, code})
      .then(data => props.onOk(data.ticket, data.expires_in))
      .finally(() => setVerifying(false))
  }

  return (
    <Modal
      visible={props.visible}
      destroyOnClose
      maskClosable={false}
      title={props.title || 'MFA安全验证'}
      okText="验证并继续"
      confirmLoading={verifying}
      onOk={handleVerify}
      onCancel={props.onCancel}>
      <Spin spinning={fetching}>
        <Alert
          showIcon
          type="warning"
          message="该操作涉及主机远程访问，必须完成MFA二次验证。"
          style={{marginBottom: 16}}/>
        <div style={{display: 'flex'}}>
          <Input
            value={code}
            maxLength={6}
            autoComplete="off"
            prefix={<SafetyCertificateOutlined/>}
            placeholder={method === 'push' ? '请输入收到的6位验证码' : '请输入身份认证器中的6位验证码'}
            onPressEnter={handleVerify}
            onChange={e => setCode(e.target.value)}/>
          {method === 'push' ? (
            <Button
              disabled={counter > 0}
              loading={fetching}
              style={{marginLeft: 8}}
              onClick={prepare}>
              {counter > 0 ? `${counter} 秒后重发` : '重新获取'}
            </Button>
          ) : null}
        </div>
      </Spin>
    </Modal>
  )
}
