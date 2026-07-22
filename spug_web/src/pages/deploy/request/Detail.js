/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, {useEffect, useState} from 'react';
import {Modal, Spin} from 'antd';
import {http} from 'libs';
import Ext1Console from './Ext1Console';
import Ext2Console from './Ext2Console';
import Ext3Console from './Ext3Console';


export default function RequestDetail({requestId, onClose}) {
  const [request, setRequest] = useState();

  useEffect(() => {
    if (!requestId) return;
    let active = true;
    setRequest(undefined);
    http.get('/api/deploy/request/info/', {params: {id: requestId}})
      .then(data => {
        if (active) setRequest({...data, mode: 'read'})
      })
      .catch(() => {
        if (active) onClose()
      });
    return () => {
      active = false
    }
  }, [requestId, onClose]);

  if (!requestId) return null;
  if (!request) {
    return (
      <Modal
        visible
        title={`发布申请 #${requestId}`}
        footer={null}
        onCancel={onClose}>
        <div style={{padding: 48, textAlign: 'center'}}><Spin tip="正在加载发布申请详情..."/></div>
      </Modal>
    )
  }

  const props = {
    key: request.id,
    request,
    onClose,
    allowMinimize: false,
    showSummary: true,
  };
  if (request.app_extend === '1') return <Ext1Console {...props}/>;
  if (request.app_extend === '3') return <Ext3Console {...props}/>;
  return <Ext2Console {...props}/>;
}
