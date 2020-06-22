# -*- encoding: utf-8 -*-
'''
@File    :   baseline.py    
@Contact :   whut.hexin@foxmail.com
@License :   (C)Copyright 2017-2020, HeXin

@Modify Time      @Author    @Version    @Desciption
------------      -------    --------    -----------
2019/11/6 18:14   xin      1.0         None
'''

from torch import nn

import torch
from .resnet_ibn_a import resnet50_ibn_a,resnet101_ibn_a

from .cosine_loss import AdaCos,ArcFace,SphereFace,CosFace,ArcCos
from .mish import Mish

def weights_init_kaiming(m):
    classname = m.__class__.__name__
    if classname.find('Linear') != -1:
        nn.init.kaiming_normal_(m.weight, a=0, mode='fan_out')
        nn.init.constant_(m.bias, 0.0)
    elif classname.find('Conv') != -1:
        nn.init.kaiming_normal_(m.weight, a=0, mode='fan_in')
        if m.bias is not None:
            nn.init.constant_(m.bias, 0.0)
    elif classname.find('BatchNorm') != -1:
        if m.affine:
            nn.init.constant_(m.weight, 1.0)
            nn.init.constant_(m.bias, 0.0)


def weights_init_classifier(m):
    classname = m.__class__.__name__
    if classname.find('Linear') != -1:
        nn.init.normal_(m.weight, std=0.001)
        if m.bias:
            nn.init.constant_(m.bias, 0.0)


class CosineBaseline(nn.Module):
    in_planes = 2048

    def __init__(self, num_classes, last_stride, model_path, backbone="resnet50_ibn_a", pool_type='avg', use_dropout=False,cosine_loss_type='ArcCos',s=30.0,m=0.35,use_bnbias=False,use_sestn=False, use_mish_convneck=True):
        super(CosineBaseline, self).__init__()
        if backbone == "resnet50":
            self.base = ResNet(last_stride)
        elif backbone == "resnet50_ibn_a":
            self.base = resnet50_ibn_a(last_stride,use_sestn=use_sestn)
        else:
            self.base = eval(backbone)(last_stride=last_stride)
        #self.base.load_param(model_path)
        print(use_mish_convneck)
        if not use_mish_convneck:
            print('not use mish')
            self.conv_neck = nn.Sequential(
                nn.Conv2d(self.in_planes, 256, 1, 1, padding=0),  # b,256,128
                nn.BatchNorm2d(256),
                nn.ReLU(True),
                )
        else:
            self.conv_neck = nn.Sequential(
                nn.Conv2d(self.in_planes, 256, 1, 1, padding=0),  # b,256,128
                nn.BatchNorm2d(256),
                Mish(),
                )
        
        in_features = 256
        
        self.gap = nn.AdaptiveAvgPool2d(1)
       

        self.num_classes = num_classes

        self.bottleneck = nn.BatchNorm1d(in_features)

        if use_bnbias == False:
            print('==> remove bnneck bias')
            self.bottleneck.bias.requires_grad_(False)  # no shift
        else:
            print('==> using bnneck bias')
        self.bottleneck.apply(weights_init_kaiming)

        if cosine_loss_type=='':
            self.classifier = nn.Linear(in_features, self.num_classes, bias=False)
            self.classifier.apply(weights_init_classifier)
        else:
            if cosine_loss_type == 'AdaCos':
                self.classifier = eval(cosine_loss_type)(in_features, self.num_classes,m)
            else:
                self.classifier = eval(cosine_loss_type)(in_features, self.num_classes,s,m)
        self.cosine_loss_type = cosine_loss_type
        # self.dropout = torch.nn.Dropout()
        self.use_dropout = use_dropout
    
        # if self.dropout >= 0:
        if use_dropout:
            self.dropout = nn.Dropout(self.dropout)
    def load_param(self, trained_path):
        param_dict = torch.load(trained_path)
        for i in param_dict:
            if 'classifier' in i:
                continue
            self.state_dict()[i].copy_(param_dict[i])
    def forward(self, x,label=None):
        x = self.base(x)
        x = self.conv_neck(x)
        global_feat = self.gap(x)  # (b, 2048, 1, 1)
        global_feat = global_feat.view(global_feat.shape[0], -1)  # flatten to (bs, 2048)
        feat = self.bottleneck(global_feat)  # normalize for angular softmax
        if self.training:
            if self.use_dropout:
                feat = self.dropout(feat)
            if self.cosine_loss_type == '':
                cls_score = self.classifier(feat)
            else:
                # assert label is not None
                cls_score = self.classifier(feat,label)
            return cls_score, global_feat  # global feature for triplet loss
        else:

            #global_feat = global_feat.div(global_feat.norm(p=2, dim=1, keepdim=True))
            return global_feat