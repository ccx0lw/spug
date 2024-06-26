/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, message, Tag } from 'antd';
import { http } from 'libs';
import store from './store';
import lds from 'lodash';
import hostStore from 'pages/host/store';
import tagStore from 'pages/config/tag/store';

export default observer(function () {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [host_ids, setHostIds] = useState([]);
  const [env, setEnv] = useState({});
  const [appTags, setAppTags] = useState([])
  useEffect(() => {
    const {app_host_ids, host_ids} = store.record;
    setHostIds(lds.clone(host_ids || app_host_ids));
    fetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
    setAppTags(tagStore.records)
  }, [])

  function fetch() {
    setLoading(true);
    const deploy_id = store.record.deploy_id
    // 获取deploy的环境信息，用于判断是否是生产环境，是否是镜像编译、后台发布
    const p3 = http.get(`/api/app/deploy/${deploy_id}/info/`, {timeout: 300000})

    Promise.all([p3, hostStore.initial()])
      .then(([res3]) => {
        setEnv(res3)
      })
      .finally(() => setLoading(false))
  }

  function handleSubmit() {
    if (host_ids.length === 0) {
      return message.error('请至少选择一个要发布的主机')
    }
    setLoading(true);
    const formData = form.getFieldsValue();
    formData['id'] = store.record.id;
    formData['deploy_id'] = store.record.deploy_id;
    formData['host_ids'] = host_ids;
    formData['type'] = "0";
    formData['extra'] = [];
    http.post('/api/deploy/request/ext3/', formData)
      .then(res => {
        message.success('操作成功');
        store.restartVisble = false;
        store.fetchRecords()
      }, () => setLoading(false))
  }

  return (
    <Modal
      visible
      width={800}
      maskClosable={false}
      title={
        <div>
          {env.env_name ? <Tag color="#108ee9">{env.env_name}</Tag> : ''}
          {store.record.id ? '编辑' : '新建'}<b>【{env.app_name}】</b>重启服务申请&ensp;
          {env.app_rel_tags?.length > 0 ? env.app_rel_tags.map(tid => (
              <Tag style={{ border: 'none' }} color="orange" key={`tag-${tid}`}>{appTags.find(item => item.id === tid).name}</Tag>
            )) : ''}
          {env.env_prod ? <Tag color="#f50">生产环境</Tag> : ''}
        </div>
      }
      onCancel={() => store.restartVisble = false}
      confirmLoading={loading}
      onOk={handleSubmit}>
      <Form form={form} initialValues={store.record} labelCol={{span: 5}} wrapperCol={{span: 17}}>
        <Form.Item required name="name" label="申请标题">
          <Input placeholder="请输入申请标题"/>
        </Form.Item>
        <Form.Item required label="目标主机" tooltip="可以通过创建多个发布申请单，选择主机分批重启。">
          {host_ids.slice(0, Math.min(3, host_ids.length)).map((id) => (
            <Tag color="#2db7f5" key={id} style={{ marginRight: 8 }}>
              {lds.get(hostStore.idMap, `${id}.name`)}[{lds.get(hostStore.idMap, `${id}.hostname`)}]
            </Tag>
          ))}
          {host_ids.length > 3 ? (<span> ... 还有{host_ids.length-3}台</span>) : (<span></span>)}
        </Form.Item>
        
        <Form.Item name="desc" label="备注信息">
          <Input placeholder="请输入备注信息"/>
        </Form.Item>
      </Form>
    </Modal>
  )
})