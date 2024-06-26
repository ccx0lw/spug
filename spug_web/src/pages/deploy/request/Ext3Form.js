/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, Select, DatePicker, Button, message, Tag } from 'antd';
import { LoadingOutlined, SyncOutlined } from '@ant-design/icons';
import HostSelector from './HostSelector';
import { http, history, includes } from 'libs';
import store from './store';
import lds from 'lodash';
import moment from 'moment';
import hostStore from 'pages/host/store';
import tagStore from 'pages/config/tag/store';

function NoVersions() {
  return (
    <div>
      <span>未找到符合条件的版本，</span>
      <Button
        type="link"
        style={{padding: 0}}
        onClick={() => history.push('/deploy/repository')}>
        去构建新版本？</Button>
    </div>
  )
}

export default observer(function () {
  const [form] = Form.useForm();
  const [visible, setVisible] = useState(false);
  const [loading, setLoading] = useState(false);
  const [repositories, setRepositories] = useState([]);
  const [images, setImages] = useState([]);
  const [host_ids, setHostIds] = useState([]);
  const [plan, setPlan] = useState(store.record.plan);
  const [fetching, setFetching] = useState(false);
  const [git_type, setGitType] = useState();
  const [extra, setExtra] = useState([]);
  const [extra1, setExtra1] = useState();
  const [extra2, setExtra2] = useState();
  const [versions, setVersions] = useState({});
  const [env, setEnv] = useState({});
  const [appTags, setAppTags] = useState([])
  useEffect(() => {
    const {app_host_ids, host_ids} = store.record;
    setHostIds(lds.clone(host_ids || app_host_ids));
    fetchVersions()
    // eslint-disable-next-line react-hooks/exhaustive-deps
    setAppTags(tagStore.records)
  }, [])

  function uniqueByUrl(arr) { 
    return arr.reduce((acc, current) => {
      const x = acc.find(item => item.url === current.url);
      if (!x) {
        return acc.concat([current]);
      } else {
        return acc;
      }
    }, []);
  };

  function fetchVersions() {
    setFetching(true);
    const deploy_id = store.record.deploy_id
    const p1 = http.get(`/api/app/deploy/${deploy_id}/versions/`, {timeout: 300000})
    const p2 = http.get('/api/repository/', {params: {deploy_id}})
    const p4 = http.get('/api/docker_image/', {params: {deploy_id}})
    // 获取deploy的环境信息，用于判断是否是生产环境，是否是镜像编译、后台发布
    const p3 = http.get(`/api/app/deploy/${deploy_id}/info/`, {timeout: 300000})

    Promise.all([p1, p2, p3, p4, hostStore.initial()])
      .then(([res1, res2, res3, res4]) => {
        setVersions(res1)
        setEnv(res3)
        var tmp = res2
        var tmp2 = res4
        if (res3?.env_prod) {
          tmp = res2.filter(item => item?.extra?.length > 0 && item?.extra[0] == 'tag')
          tmp2 = res4.filter(item => item?.extra?.length > 0 && (item?.extra[0] == 'tag' || (item?.extra[0] == 'repository') && item?.extra[1] == 'tag'))
        }
        if (!versions.branches) _initial(res1, tmp, res3, tmp2)
        setRepositories(tmp)
        setImages(uniqueByUrl(tmp2))
      })
      .finally(() => setFetching(false))
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
    formData['type'] = store.record.type;
    formData['extra'] = [git_type, extra1, extra2];
    if (plan) formData.plan = plan.format('YYYY-MM-DD HH:mm:00');
    http.post('/api/deploy/request/ext3/', formData)
      .then(res => {
        message.success('操作成功');
        store.ext3Visible = false;
        store.fetchRecords()
      }, () => setLoading(false))
  }

  function _setDefault(type, new_extra, new_versions, new_repositories, new_images) {
    const now_extra = new_extra || extra;
    const now_versions = new_versions || versions;
    const now_repositories = new_repositories || repositories;
    const now_images = new_images || images;
    const {branches, tags} = now_versions;
    if (type === 'branch') {
      let [branch, commit] = [now_extra[1], null];
      if (branches[branch]) {
        commit = lds.get(branches[branch], '0.id')
      } else {
        branch = lds.get(Object.keys(branches), 0)
        commit = lds.get(branches, [branch, 0, 'id'])
      }
      setExtra1(branch)
      setExtra2(commit)
    } else if (type === 'tag') {
      setExtra1(lds.get(Object.keys(tags), 0))
      setExtra2(null)
    } else if (type === 'docker_image') {
      setExtra1(lds.get(now_images, '0.id'))
      setExtra2(null)
    } else {
      setExtra1(lds.get(now_repositories, '0.id'))
      setExtra2(null)
    }
  }

  function _initial(versions, repositories, env, images) {
    if (env.env_prod) {
      return _setDefault('tags', null, null, null)
    }

    const {branches, tags} = versions;
    if (branches && tags) {
      for (let item of store.records) {
        if (item.extra && item.deploy_id === store.record.deploy_id) {
          const type = item.extra[0];
          setExtra(item.extra);
          setGitType(type);
          return _setDefault(type, item.extra, versions, repositories, images);
        }
      }
      setGitType('branch');
      const branch = lds.get(Object.keys(branches), 0);
      const commit = lds.get(branches, [branch, 0, 'id'])
      setExtra1(branch);
      setExtra2(commit)
    }
  }

  function switchType(v) {
    setGitType(v);
    _setDefault(v)
  }

  function switchExtra1(v) {
    setExtra1(v)
    if (git_type === 'branch') {
      setExtra2(lds.get(versions.branches[v], '0.id'))
    }
  }

  function extractImageDetails(fullString) {
    // 使用 '/' 分割字符串以获取镜像名称和版本的部分
    const parts = fullString.split('/');
    // 获取最后一个部分，它包含镜像名称和版本
    const imagePart = parts[parts.length - 1];
    return imagePart;
  }

  const {app_host_ids, type, rb_id} = store.record;
  const {branches, tags} = versions;
  return (
    <Modal
      visible
      width={800}
      maskClosable={false}
      title={
        <div>
          {env.env_name ? <Tag color="#108ee9">{env.env_name}</Tag> : ''}
          {store.record.id ? '编辑' : '新建'}<b>【{env.app_name}】</b>发布申请&ensp;
          {env.app_rel_tags?.length > 0 ? env.app_rel_tags.map(tid => (
              <Tag style={{ border: 'none' }} color="orange" key={`tag-${tid}`}>{appTags.find(item => item.id === tid).name}</Tag>
            )) : ''}
          {env.env_prod ? <Tag color="#f50">生产环境</Tag> : ''}
        </div>
      }
      onCancel={() => store.ext3Visible = false}
      confirmLoading={loading}
      onOk={handleSubmit}>
      <Form form={form} initialValues={store.record} labelCol={{span: 5}} wrapperCol={{span: 17}}>
        <Form.Item required name="name" label="申请标题">
          <Input placeholder="请输入申请标题"/>
        </Form.Item>
        <Form.Item required label="分支/标签/版本/镜像" style={{marginBottom: 12}} extra={<span>
            {git_type === 'docker_image' ? <p>镜像只可以选择最近的3个, 如果镜像URL重复只会展示一个。 列表展示的是 [代码版本 镜像名称:镜像版本 镜像编译上传时间]</p> : null}
            根据网络情况，首次刷新可能会很慢，请耐心等待。
            <a target="_blank" rel="noopener noreferrer"
               href="https://spug.cc/docs/use-problem#clone">clone 失败？</a>
          </span>}>
          <Form.Item style={{display: 'inline-block', marginBottom: 0, width: '450px'}}>
            <Input.Group compact>
              <Select value={git_type} onChange={switchType} style={{width: 100}}>
                <Select.Option value="branch" disabled={env.env_prod}>Branch</Select.Option>
                <Select.Option value="tag">Tag</Select.Option>
                <Select.Option value="repository">构建仓库</Select.Option>
                <Select.Option value="docker_image">镜像</Select.Option>
              </Select>
              <Select
                showSearch
                style={{width: 350}}
                value={extra1}
                placeholder="请稍等"
                onChange={switchExtra1}
                notFoundContent={git_type === 'repository' ? <NoVersions/> : undefined}
                filterOption={(input, option) => includes(option.content, input)}>
                {git_type === 'branch' ? (
                  Object.keys(branches || {}).map(b => (
                    <Select.Option key={b} value={b} content={b}>{b}</Select.Option>
                  ))
                ) : git_type === 'tag' ? (
                  Object.entries(tags || {}).map(([tag, info]) => (
                    <Select.Option key={tag} value={tag} content={`${tag} ${info.author} ${info.message}`}>
                      <div style={{display: 'flex', justifyContent: 'space-between'}}>
                        <span style={{
                          width: 200,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis'
                        }}>{`${tag} ${info.author} ${info.message}`}</span>
                        <span style={{color: '#999', fontSize: 12}}>{info['date']} </span>
                      </div>
                    </Select.Option>
                  ))
                ) : git_type === 'repository' ? (
                  repositories.map(item => (
                    <Select.Option key={item.id} value={item.id} content={item.version}
                                   disabled={type === '2' && item.id >= rb_id}>
                      <div style={{display: 'flex', justifyContent: 'space-between'}}>
                        <span>{item.version}</span>
                        <span style={{color: '#999', fontSize: 12}}>构建于 {moment(item.created_at).fromNow()}</span>
                      </div>
                    </Select.Option>
                  ))
                ) : git_type === 'docker_image' ? (
                  images.map(item => (
                    <Select.Option key={item.id} value={item.id} content={item.version} url={item.url}>
                      <div style={{display: 'flex', justifyContent: 'space-between'}}>
                        <span style={{
                            width: 200,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis'
                          }}>{` ${item.version} ${extractImageDetails(item.url)}`}</span>
                        <span style={{color: '#999', fontSize: 12}}>编译于 {moment(item.created_at).fromNow()}</span>
                      </div>
                    </Select.Option>
                  ))
                ) : null
              }
              </Select>
            </Input.Group>
          </Form.Item>
          <Form.Item style={{display: 'inline-block', width: 82, textAlign: 'center', marginBottom: 0}}>
            {fetching ? <LoadingOutlined style={{fontSize: 18, color: '#1890ff'}}/> :
              <Button type="link" icon={<SyncOutlined/>} disabled={fetching} onClick={fetchVersions}>刷新</Button>
            }
          </Form.Item>
        </Form.Item>
        {git_type === 'docker_image' && (
            <Form.Item label="镜像地址" tooltip=":后面的是版本号">
              {images.map(item => 
              item.id === extra1 && (
                <div key={item.id}>
                  <span>{item.url}</span>
                </div>
              ))}
            </Form.Item>
        )}
        {git_type === 'branch' && (
          <Form.Item required label="选择Commit ID">
            <Select value={extra2} placeholder="请选择" onChange={v => setExtra2(v)}>
              {extra1 && branches ? branches[extra1].map(item => (
                <Select.Option key={item.id}>
                  <div style={{display: 'flex', justifyContent: 'space-between'}}>
                    <span style={{
                      width: 400,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis'
                    }}>{item.id.substr(0, 6)} {item['author']} {item['message']}</span>
                    <span style={{color: '#999', fontSize: 12}}>{item['date']} </span>
                  </div>
                </Select.Option>
              )) : null}
            </Select>
          </Form.Item>
        )}
        <Form.Item required label="目标主机" tooltip="可以通过创建多个发布申请单，选择主机分批发布。">
          {/*{host_ids.length > 0 && (
            <span style={{marginRight: 16}}>已选择 {host_ids.length} 台（可选{app_host_ids.length}）</span>
          )}*/}
          <span>
          {host_ids.slice(0, Math.min(3, host_ids.length)).map((id) => (
            <Tag color="#2db7f5" key={id} style={{ marginRight: 8 }}>
              {lds.get(hostStore.idMap, `${id}.name`)}[{lds.get(hostStore.idMap, `${id}.hostname`)}]
            </Tag>
          ))}
          </span>
          {host_ids.length > 3 ? (<span> ... 还有{host_ids.length-3}台</span>) : (<span></span>)}
          {/* <Button disabled={true} type="link" style={{padding: 0}} onClick={() => setVisible(true)}>选择主机</Button> */}
        </Form.Item>
        
        <Form.Item name="desc" label="备注信息">
          <Input placeholder="请输入备注信息"/>
        </Form.Item>
        {type !== '2' && (
          <Form.Item label="定时发布" tooltip="在到达指定时间后自动发布，会有最多1分钟的延迟。">
            <DatePicker
              showTime
              value={plan}
              style={{width: 180}}
              format="YYYY-MM-DD HH:mm"
              placeholder="请设置发布时间"
              onChange={setPlan}/>
            {plan ? <span style={{marginLeft: 24, fontSize: 12, color: '#888'}}>大约 {plan.fromNow()}</span> : null}
          </Form.Item>
        )}
      </Form>
      {visible && <HostSelector
        host_ids={host_ids}
        app_host_ids={app_host_ids}
        onCancel={() => setVisible(false)}
        onOk={ids => setHostIds(ids)}/>}
    </Modal>
  )
})